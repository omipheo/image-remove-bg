import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { uploadImageToBackend, downloadImageFromBackend } from '../services/api'
import { readImageAsDataURL, downloadFile, generateDownloadFilename, dataURLToBlob } from '../utils/fileUtils'
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

  const processImage = async (file, backgroundColor, fileType) => {
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
        
        setImageUrl(result.imageUrl)
        setImageId(result.imageId)
        setIsLoading(false)
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

  const processMultipleImages = async (files, backgroundColor, fileType) => {
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
      await processImage(imageFiles[0], backgroundColor, fileType)
      
      if (isCancelledRef.current) {
        return
      }
    }

    // Process remaining images in background
    if (imageFiles.length > 1) {
      setIsLoading(true)
      // Clear previous processed images
      setProcessedImages([])

      for (let i = 1; i < imageFiles.length; i++) {
        if (isCancelledRef.current) {
          break
        }

        try {
          const file = imageFiles[i]
          const originalUrl = await readImageAsDataURL(file)

          if (isCancelledRef.current) {
            break
          }

          if (API_CONFIG.USE_BACKEND) {
            const result = await uploadImageToBackend(file, backgroundColor, fileType, abortControllerRef.current.signal)
            
            if (isCancelledRef.current) {
              break
            }
            
            // Add image to state immediately as it's processed
            const newImage = {
              file,
              originalUrl,
              processedUrl: result.imageUrl,
              imageId: result.imageId
            }
            
            // Use functional update to add to existing array
            setProcessedImages(prev => [...prev, newImage])
          } else {
            // Add image to state immediately as it's processed
            const newImage = {
              file,
              originalUrl,
              processedUrl: originalUrl
            }
            
            // Use functional update to add to existing array
            setProcessedImages(prev => [...prev, newImage])
          }
        } catch (err) {
          if (err.name === 'AbortError' || isCancelledRef.current) {
            break
          }
          console.error(`Error processing ${imageFiles[i].name}:`, err)
        }
      }

      setIsLoading(false)
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

  const downloadImage = async (fileType) => {
    if (!imageUrl) return

    try {
      if (API_CONFIG.USE_BACKEND) {
        if (!imageId) {
          throw new Error('No image ID available')
        }
        const blob = await downloadImageFromBackend(imageId, fileType)
        const filename = generateDownloadFilename(currentFile?.name || 'image.png', fileType)
        downloadFile(blob, filename)
      } else {
        const filename = currentFile?.name || 'downloaded-image.png'
        downloadFile(imageUrl, filename)
      }
    } catch (err) {
      setError(err.message)
    }
  }

  const downloadProcessedImage = async (item, fileType) => {
    try {
      if (API_CONFIG.USE_BACKEND && item.imageId) {
        const blob = await downloadImageFromBackend(item.imageId, fileType)
        const filename = generateDownloadFilename(item.file.name, fileType)
        downloadFile(blob, filename)
      } else {
        downloadFile(item.processedUrl, item.file.name)
      }
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
            if (API_CONFIG.USE_BACKEND && item.imageId) {
              console.log(`Downloading image ${i + 1}/${imagesToDownload.length} from backend:`, item.imageId)
              blob = await downloadImageFromBackend(item.imageId, fileType)
            } else {
              // Convert data URL to blob
              if (item.url && item.url.startsWith('data:')) {
                console.log(`Converting data URL to blob for image ${i + 1}/${imagesToDownload.length}`)
                blob = dataURLToBlob(item.url)
              } else if (item.url) {
                // If it's already a URL, fetch it
                console.log(`Fetching image ${i + 1}/${imagesToDownload.length} from URL`)
                const response = await fetch(item.url)
                blob = await response.blob()
              } else {
                throw new Error(`No valid URL or imageId for image ${i + 1}`)
              }
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
          
          if (API_CONFIG.USE_BACKEND && item.imageId) {
            const blob = await downloadImageFromBackend(item.imageId, fileType)
            const filename = generateDownloadFilename(item.file.name, fileType)
            downloadFile(blob, filename)
          } else {
            const filename = generateDownloadFilename(item.file.name, fileType)
            downloadFile(item.url, filename)
          }
          
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

