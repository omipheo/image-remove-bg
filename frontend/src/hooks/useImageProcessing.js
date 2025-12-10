import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { uploadImageToBackend, downloadImageFromBackend } from '../services/api'
import { ImageProcessingWebSocket } from '../services/websocketService'
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

  const processMultipleImages = async (files, backgroundColor, fileType, watermark = 'none', downloadMode = 'manual') => {
    // Batch size is fixed at 100 images per batch
    const BATCH_SIZE = 100
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
        // Use WebSocket for pipelined processing
        try {
          // Read original URLs for all images
          const originalUrlsMap = new Map()
          await Promise.all(remainingImages.map(async (file) => {
            const originalUrl = await readImageAsDataURL(file)
            originalUrlsMap.set(file, originalUrl)
          }))
          
          if (isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          
          // Create WebSocket connection
          const ws = new ImageProcessingWebSocket(
            // onResult - called for each processed image (streaming)
            async (result) => {
              if (result.type === 'image_processed' && result.success) {
                try {
                  // Download image from backend
                  const downloadUrl = result.downloadUrl
                  
                  // Add null check for downloadUrl
                  if (!downloadUrl) {
                    console.error('No download URL in result:', result)
                    return
                  }
                  
                  const fullUrl = downloadUrl.startsWith('http') 
                    ? downloadUrl 
                    : `${API_CONFIG.BASE_URL}${downloadUrl}`
                  
                  const response = await fetch(fullUrl)
                  if (!response.ok) throw new Error(`Download failed: ${response.statusText}`)
                  
                  const imageBlob = await response.blob()
                  const processedUrl = URL.createObjectURL(imageBlob)
                  
                  // Find corresponding file using WebSocket service mapping
                  const file = ws.getFileForResult(result)
                  
                  // Add null check for file
                  if (!file) {
                    console.error('Could not find file for result:', result)
                    return
                  }
                  
                  const originalUrl = originalUrlsMap.get(file)
                  
                  // Add null check for originalUrl
                  if (!originalUrl) {
                    console.error('No original URL found for file:', file.name)
                    return
                  }
                  
                  let finalUrl = processedUrl
                  
                  // Apply watermark if needed
                  if (watermark === 'blog') {
                    finalUrl = await addWatermark(processedUrl, backgroundColor)
                  }
                  
                  const processedImage = {
                    file,
                    originalUrl,
                    processedUrl: finalUrl,
                    imageId: result.imageId
                  }
                  
                  allProcessedImagesForDownload.push(processedImage)
                  setProcessedImages(prev => [...prev, processedImage])
                } catch (err) {
                  console.error(`Error processing result for image ${result.taskId}:`, err)
                }
              }
            },
                        // onError
            (error) => {
              console.error('[WS] Error:', error)
              setError(error.message || 'WebSocket error')
              setIsLoading(false)
            },
            // onClose
            () => {
              console.log('[WS] Closed')
              setIsLoading(false)
            }
          )
          
          // Connect WebSocket
          await ws.connect(backgroundColor, fileType, watermark, BATCH_SIZE)
          
          // Split into batches of 100
          const batches = []
          for (let i = 0; i < remainingImages.length; i += BATCH_SIZE) {
            batches.push(remainingImages.slice(i, i + BATCH_SIZE))
          }
          
          // Pipeline workflow: Upload batch 0 → Process batch 0 (while uploading batch 1) → etc.
          for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
            if (isCancelledRef.current) break
            
            const batch = batches[batchIndex]
            const batchId = batchIndex
            
            if (batchIndex === 0) {
              // First batch: upload immediately
              console.log(`[WS] Uploading batch ${batchId} (${batch.length} images)`)
              await ws.sendBatch(batch, batchId)
              
              // Wait for batch_queued (GPU started processing) - this signals we can upload next batch
              let waitCount = 0
              while (!ws.batchQueued.has(batchId) && waitCount < 200) {
                await new Promise(resolve => setTimeout(resolve, 50))
                waitCount++
              }
              
              if (ws.batchQueued.has(batchId)) {
                console.log(`[WS] Batch ${batchId} queued - GPU processing started, can upload next batch`)
              } else {
                console.warn(`[WS] Batch ${batchId} upload complete but batch_queued not received (timeout)`)
              }
            } else {
              // For subsequent batches: wait for previous batch to be queued (processing started)
              // This ensures we upload next batch while previous is processing (pipelining)
              const prevBatchId = batchIndex - 1
              console.log(`[WS] Waiting for batch ${prevBatchId} to be queued before uploading batch ${batchId}...`)
              let waitCount = 0
              while (!ws.batchQueued.has(prevBatchId) && waitCount < 200) {
                await new Promise(resolve => setTimeout(resolve, 50))
                waitCount++
                if (waitCount % 20 === 0) {
                  console.log(`[WS] Still waiting for batch ${prevBatchId} to be queued... (${waitCount * 50}ms)`)
                }
              }
              
              if (ws.batchQueued.has(prevBatchId)) {
                // Now upload this batch (previous batch is already processing)
                console.log(`[WS] Batch ${prevBatchId} is processing, uploading batch ${batchId} (${batch.length} images)`)
                await ws.sendBatch(batch, batchId)
                
                // Wait for this batch to be queued (processing started)
                waitCount = 0
                while (!ws.batchQueued.has(batchId) && waitCount < 200) {
                  await new Promise(resolve => setTimeout(resolve, 50))
                  waitCount++
                }
                
                if (ws.batchQueued.has(batchId)) {
                  console.log(`[WS] Batch ${batchId} queued - GPU processing started`)
                } else {
                  console.warn(`[WS] Batch ${batchId} upload complete but batch_queued not received (timeout)`)
                }
              } else {
                console.error(`[WS] Timeout waiting for batch ${prevBatchId} to be queued. Uploading batch ${batchId} anyway...`)
                await ws.sendBatch(batch, batchId)
              }
            }
          }
          
          // Wait for all batches to complete processing
          // Keep WebSocket open to receive all results
          console.log('[WS] All batches uploaded, waiting for processing results...')
          
          // Wait for all batches to complete
          const totalBatches = batches.length
          let waitCount = 0
          const maxWait = 600  // 60 seconds max wait (10 seconds per batch * 6 batches)
          
          while (ws.batchComplete.size < totalBatches && waitCount < maxWait) {
            if (isCancelledRef.current) break
            await new Promise(resolve => setTimeout(resolve, 100))
            waitCount++
            
            // Log progress every 5 seconds
            if (waitCount % 50 === 0) {
              console.log(`[WS] Waiting for results: ${ws.batchComplete.size}/${totalBatches} batches complete`)
            }
          }
          
          if (ws.batchComplete.size >= totalBatches) {
            console.log('[WS] All batches processing complete!')
          } else {
            console.log(`[WS] Timeout waiting for all batches (${ws.batchComplete.size}/${totalBatches} complete)`)
          }
          
          // Don't close WebSocket here - let it stay open for a bit more to catch any late results
          // The WebSocket will be closed when the component unmounts or user cancels
          
        } catch (err) {
          if (err.name === 'AbortError' || isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          console.error('Error in WebSocket processing:', err)
          
          // If WebSocket fails, provide helpful error message
          let errorMessage = err.message || 'Error processing images'
          if (errorMessage.includes('WebSocket connection failed')) {
            errorMessage = 'WebSocket connection failed. The server may not be configured to handle WebSocket connections. Please contact the administrator.'
          }
          
          setError(errorMessage)
          setIsLoading(false)
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

