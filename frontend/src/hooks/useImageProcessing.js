import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { uploadImageToBackend, uploadImagesBatchToBackend, downloadImageFromBackend } from '../services/api'
import { readImageAsDataURL, downloadFile, generateDownloadFilename, dataURLToBlob, addWatermark } from '../utils/fileUtils'
import { API_CONFIG } from '../config/api'

export const useImageProcessing = () => {
  const [imageUrl, setImageUrl] = useState(null)
  const [originalImageUrl, setOriginalImageUrl] = useState(null)
  const [currentFile, setCurrentFile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [imageId, setImageId] = useState(null)
  const [processedImages, setProcessedImages] = useState([])
  const abortControllerRef = useRef(null)
  const isCancelledRef = useRef(false)

  const processImage = async (file, backgroundColor, fileType, watermark = 'none', downloadMode = 'manual') => {
    if (!file) return

    // Reset cancellation flag
    isCancelledRef.current = false
    abortControllerRef.current = new AbortController()

    setCurrentFile(file)
    setIsLoading(true)
    setImageUrl(null)
    setOriginalImageUrl(null)
    setError(null)
    setImageId(null)

    try {
      // Read and display original image first
      const originalUrl = await readImageAsDataURL(file)
      
      if (isCancelledRef.current) {
        setIsLoading(false)
        return
      }
      
      setOriginalImageUrl(originalUrl)

      if (API_CONFIG.USE_BACKEND) {
        // Backend mode
        const result = await uploadImageToBackend(file, backgroundColor, fileType, abortControllerRef.current.signal)
        
        if (isCancelledRef.current) {
          setIsLoading(false)
          return
        }
        
        // Apply watermark if needed
        let finalImageUrl = result.imageUrl
        if (watermark === 'blog') {
          finalImageUrl = await addWatermark(result.imageUrl, backgroundColor)
        }
        
        setImageUrl(finalImageUrl)
        setImageId(result.imageId)
        setIsLoading(false)
        
        // Auto-download if enabled
        if (downloadMode === 'automatic') {
          // Small delay to ensure UI updates and state is set
          setTimeout(async () => {
            try {
              // Use the finalImageUrl directly instead of relying on state
              const blob = dataURLToBlob(finalImageUrl)
              const filename = generateDownloadFilename(file.name || 'image.png', fileType)
              downloadFile(blob, filename)
              console.log('Auto-download triggered:', filename)
            } catch (err) {
              console.error('Auto-download failed:', err)
              // Fallback: try again after a bit more delay to ensure state is ready
              setTimeout(() => {
                downloadImage(fileType)
              }, 500)
            }
          }, 800) // Increased delay to ensure state is updated
        }
      } else {
        // Local mode
        if (isCancelledRef.current) {
          setIsLoading(false)
          return
        }
        setImageUrl(originalUrl)
        setIsLoading(false)
      }
    } catch (err) {
      if (err.name === 'AbortError' || isCancelledRef.current) {
        setError('Processing cancelled')
      } else {
        setError(err.message)
      }
      setIsLoading(false)
    }
  }

  const processMultipleImages = async (files, backgroundColor, fileType, watermark = 'none', downloadMode = 'manual', concurrency = 3) => {
    const imageFiles = files.filter(file => file.type.startsWith('image/'))
    if (imageFiles.length === 0) {
      setError('Please select at least one image file')
      return
    }

    // Reset cancellation flag
    isCancelledRef.current = false
    abortControllerRef.current = new AbortController()

    setError(null)
    setProcessedImages([])

    // Process first image immediately for single image view
    if (imageFiles.length > 0) {
      // For single image, don't auto-download here (it will be handled in processImage)
      await processImage(imageFiles[0], backgroundColor, fileType, watermark, imageFiles.length === 1 ? downloadMode : 'manual')
      
      if (isCancelledRef.current) {
        return
      }
    }

    // Process remaining images using batch upload
    if (imageFiles.length > 1) {
      setIsLoading(true)
      // Clear previous processed images
      setProcessedImages([])
      
      // Collect all processed images for auto-download
      const allProcessedImagesForDownload = []
      
      // Get remaining images (skip first one as it's already processed)
      const remainingImages = imageFiles.slice(1)
      
      if (API_CONFIG.USE_BACKEND) {
        // Use batch upload for all remaining images
        try {
          // Read original URLs for all remaining images first
          const originalUrlsMap = new Map()
          await Promise.all(remainingImages.map(async (file) => {
            const originalUrl = await readImageAsDataURL(file)
            originalUrlsMap.set(file, originalUrl)
          }))
          
          if (isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          
          // Process remaining images in batches based on concurrency setting
          const batchSize = Math.max(1, Math.min(concurrency, 100)) // Clamp between 1 and 100
          
          for (let i = 0; i < remainingImages.length; i += batchSize) {
            if (isCancelledRef.current) {
              break
            }
            
            const batch = remainingImages.slice(i, i + batchSize)
            
            // Upload batch to backend
            const batchResult = await uploadImagesBatchToBackend(
              batch,
              backgroundColor,
              fileType,
              abortControllerRef.current.signal
            )
            
            if (isCancelledRef.current) {
              break
            }
            
            // Process results and apply watermarks
            for (let j = 0; j < batchResult.results.length; j++) {
              const result = batchResult.results[j]
              const file = batch[j]
              
              if (result.error) {
                console.error(`Error processing ${file.name}:`, result.error)
                continue
              }
              
              const originalUrl = originalUrlsMap.get(file)
              
              // Apply watermark if needed
              let processedUrl = result.imageUrl
              if (watermark === 'blog') {
                processedUrl = await addWatermark(result.imageUrl, backgroundColor)
              }
              
              const processedImage = {
                file,
                originalUrl,
                processedUrl: processedUrl,
                imageId: result.imageId
              }
              
              allProcessedImagesForDownload.push(processedImage)
              setProcessedImages(prev => [...prev, processedImage])
            }
          }
        } catch (err) {
          if (err.name === 'AbortError' || isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          console.error('Error in batch processing:', err)
          setError(err.message || 'Error processing images')
        }
      } else {
        // Local mode - just use original images
        const localResults = remainingImages.map(file => ({
          file,
          originalUrl: null,
          processedUrl: null
        }))
        allProcessedImagesForDownload.push(...localResults)
        setProcessedImages(localResults)
      }

      setIsLoading(false)
      
      // Auto-download if enabled (for multiple images, download all as ZIP)
      if (downloadMode === 'automatic' && !isCancelledRef.current) {
        // Small delay to ensure UI updates
        setTimeout(async () => {
          try {
            // Create ZIP with all images
            const zip = new JSZip()
            const imagesToZip = []
            
            // Add first image (from imageUrl state)
            if (imageUrl && currentFile) {
              imagesToZip.push({
                url: imageUrl,
                file: currentFile
              })
            }
            
            // Add all remaining processed images
            allProcessedImagesForDownload.forEach(item => {
              imagesToZip.push({
                url: item.processedUrl,
                file: item.file
              })
            })
            
            if (imagesToZip.length === 0) {
              console.warn('No processed images found for auto-download')
              return
            }
            
            // Create ZIP
            for (let i = 0; i < imagesToZip.length; i++) {
              const item = imagesToZip[i]
              try {
                const blob = dataURLToBlob(item.url)
                const filename = generateDownloadFilename(item.file.name, fileType)
                zip.file(filename, blob)
              } catch (err) {
                console.error(`Error adding ${item.file.name} to ZIP:`, err)
              }
            }
            
            // Generate and download ZIP
            if (Object.keys(zip.files).length > 0) {
              const zipBlob = await zip.generateAsync({ 
                type: 'blob',
                compression: 'DEFLATE',
                compressionOptions: { level: 6 }
              })
              const zipFilename = `processed-images-${new Date().toISOString().slice(0, 10)}.zip`
              downloadFile(zipBlob, zipFilename)
              console.log('Auto-download ZIP triggered:', zipFilename, `(${Object.keys(zip.files).length} images)`)
            }
          } catch (err) {
            console.error('Auto-download failed:', err)
          }
        }, 1000) // Delay to ensure state is updated
      }
    }
  }

  const stopProcessing = () => {
    isCancelledRef.current = true
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    setIsLoading(false)
    setError('Processing stopped by user')
  }

  const downloadImage = async (fileType, watermark = 'none') => {
    if (!imageUrl) return

    try {
      // Use the displayed image URL which already has watermark applied
      const blob = dataURLToBlob(imageUrl)
      const filename = generateDownloadFilename(currentFile?.name || 'image.png', fileType)
      downloadFile(blob, filename)
    } catch (err) {
      setError(err.message)
    }
  }

  const downloadProcessedImage = async (item, fileType) => {
    try {
      // Use the displayed processed URL which already has watermark applied
      const blob = dataURLToBlob(item.processedUrl)
      const filename = generateDownloadFilename(item.file.name, fileType)
      downloadFile(blob, filename)
    } catch (err) {
      setError(`Failed to download ${item.file.name}: ${err.message}`)
    }
  }

  const downloadAllProcessedImages = async (fileType, asZip = false) => {
    const imagesToDownload = []
    
    // Add main processed image if available
    if (imageUrl && currentFile) {
      imagesToDownload.push({
        url: imageUrl,
        file: currentFile,
        imageId: imageId
      })
    }
    
    // Add all processed images from the array
    if (processedImages && processedImages.length > 0) {
      processedImages.forEach(item => {
        imagesToDownload.push({
          url: item.processedUrl,
          file: item.file,
          imageId: item.imageId
        })
      })
    }
    
    if (imagesToDownload.length === 0) {
      setError('No processed images to download')
      return
    }
    
    try {
      if (asZip) {
        // Download as ZIP file
        console.log('Creating ZIP file with', imagesToDownload.length, 'images')
        const zip = new JSZip()
        
        for (let i = 0; i < imagesToDownload.length; i++) {
          const item = imagesToDownload[i]
          let blob
          
          try {
            // Use the watermarked URL from state (already has watermark applied)
            if (item.url && item.url.startsWith('data:')) {
              console.log(`Converting data URL to blob for image ${i + 1}/${imagesToDownload.length}`)
              blob = dataURLToBlob(item.url)
            } else if (item.url) {
              // If it's already a URL, fetch it
              console.log(`Fetching image ${i + 1}/${imagesToDownload.length} from URL`)
              const response = await fetch(item.url)
              blob = await response.blob()
            } else {
              throw new Error(`No valid URL for image ${i + 1}`)
            }
            
            if (!blob || blob.size === 0) {
              throw new Error(`Failed to get blob for image ${i + 1}`)
            }
            
            const filename = generateDownloadFilename(item.file.name, fileType)
            console.log(`Adding to ZIP: ${filename} (${blob.size} bytes)`)
            zip.file(filename, blob)
          } catch (err) {
            console.error(`Error processing image ${i + 1} (${item.file?.name}):`, err)
            // Continue with other images even if one fails
          }
        }
        
        // Check if ZIP has any files
        const fileCount = Object.keys(zip.files).length
        if (fileCount === 0) {
          throw new Error('No images were successfully added to the ZIP file')
        }
        
        console.log(`Generating ZIP file with ${fileCount} images`)
        // Generate ZIP file
        const zipBlob = await zip.generateAsync({ 
          type: 'blob',
          compression: 'DEFLATE',
          compressionOptions: { level: 6 }
        })
        
        console.log(`ZIP file generated: ${zipBlob.size} bytes`)
        const zipFilename = `processed-images-${new Date().toISOString().slice(0, 10)}.zip`
        downloadFile(zipBlob, zipFilename)
        console.log(`ZIP file download initiated: ${zipFilename}`)
      } else {
        // Download all images individually with a small delay between each
        for (let i = 0; i < imagesToDownload.length; i++) {
          const item = imagesToDownload[i]
          
          // Use the watermarked URL from state (already has watermark applied)
          const blob = dataURLToBlob(item.url)
          const filename = generateDownloadFilename(item.file.name, fileType)
          downloadFile(blob, filename)
          
          // Small delay between downloads to prevent browser from blocking multiple downloads
          if (i < imagesToDownload.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 200))
          }
        }
      }
    } catch (err) {
      setError(`Failed to download all images: ${err.message}`)
    }
  }

  const reset = () => {
    setImageUrl(null)
    setOriginalImageUrl(null)
    setCurrentFile(null)
    setImageId(null)
    setProcessedImages([])
    setError(null)
  }

  return {
    // State
    imageUrl,
    originalImageUrl,
    currentFile,
    isLoading,
    error,
    imageId,
    processedImages,
    // Actions
    processImage,
    processMultipleImages,
    downloadImage,
    downloadProcessedImage,
    downloadAllProcessedImages,
    stopProcessing,
    setError,
    reset
  }
}

