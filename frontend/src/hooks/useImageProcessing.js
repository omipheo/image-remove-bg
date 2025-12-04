import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { uploadImageToBackend, uploadImagesBatchToBackend, downloadImageFromBackend, downloadImagesAsZip, ImageProcessingWebSocket } from '../services/api'
import { readImageAsDataURL, downloadFile, generateDownloadFilename, dataURLToBlob, blobURLToDataURL, addWatermark } from '../utils/fileUtils'
import { API_CONFIG } from '../config/api'

export const useImageProcessing = () => {
  const [imageUrl, setImageUrl] = useState(null)
  const [originalImageUrl, setOriginalImageUrl] = useState(null)
  const [currentFile, setCurrentFile] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [imageId, setImageId] = useState(null)
  const [processedImages, setProcessedImages] = useState([])
  const [progress, setProgress] = useState({ processed: 0, total: 0, percentage: 0, currentBatch: 0, totalBatches: 0 })
  const [isDownloading, setIsDownloading] = useState(false)
  const abortControllerRef = useRef(null)
  const isCancelledRef = useRef(false)
  const wsRef = useRef(null) // WebSocket reference for streaming
  const autoDownloadTriggeredRef = useRef(false) // Track if auto-download has been triggered for this session
  const sessionZipUrlRef = useRef(null) // Store the ZIP URL for the current session

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
    setProgress({ processed: 0, total: 1, percentage: 0, currentBatch: 0, totalBatches: 0 })

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
        
        // Ensure we use data URL (not blob URL) for secure display
        if (finalImageUrl && finalImageUrl.startsWith('blob:')) {
          finalImageUrl = await blobURLToDataURL(finalImageUrl)
        }
        
        if (watermark === 'blog') {
          finalImageUrl = await addWatermark(finalImageUrl, backgroundColor)
        }
        
        // Ensure final URL is data URL (not blob URL) to avoid mixed content warnings
        if (finalImageUrl && finalImageUrl.startsWith('blob:')) {
          finalImageUrl = await blobURLToDataURL(finalImageUrl)
        }
        
        setImageUrl(finalImageUrl)
        setImageId(result.imageId)
        setIsLoading(false)
        setProgress({ processed: 1, total: 1, percentage: 100, currentBatch: 1, totalBatches: 1 })
        
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

    // Process remaining images using WebSocket streaming (continuous processing)
    if (imageFiles.length > 1) {
      setIsLoading(true)
      // Clear previous processed images
      setProcessedImages([])
      
      // Collect all processed images for download (metadata only, no UI display)
      const allProcessedImagesForDownload = []
      
      // Include first image in download list
      if (imageUrl && currentFile && imageId) {
        allProcessedImagesForDownload.push({
          file: currentFile,
          imageId: imageId,
          downloadUrl: `/api/download?imageId=${imageId}`,
          format: fileType,
          filename: currentFile.name
        })
      }
      
      // Reset auto-download flag and ZIP URL for new processing session
      autoDownloadTriggeredRef.current = false
      sessionZipUrlRef.current = null
      
      // Get remaining images (skip first one as it's already processed and displayed)
      const remainingImages = imageFiles.slice(1)
      
      // Pre-load original image URLs for all remaining images
      const originalImageUrls = new Map() // filename -> dataUrl
      // Also create a Map to track file references by taskId (set before sending)
      const fileReferenceMap = new Map() // taskId -> { file, originalUrl }
      
      for (const file of remainingImages) {
        try {
            const originalUrl = await readImageAsDataURL(file)
          originalImageUrls.set(file.name, originalUrl)
        } catch (err) {
          console.error(`Error reading original image ${file.name}:`, err)
        }
      }
      
      if (API_CONFIG.USE_BACKEND && remainingImages.length > 0) {
        // Use WebSocket for continuous streaming processing (GPU always busy)
        try {
          if (isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          
          // Track total images to process (first image + remaining images)
          const totalImages = 1 + remainingImages.length // First image already processed
          
          // Create WebSocket connection for streaming
          const ws = new ImageProcessingWebSocket(
            // onResult callback - called when each image is processed or batch is complete
            async (result) => {
              console.log('[onResult] Received result:', result)
              
              // Handle batch_complete message (trigger auto-download only after ALL batches are complete)
              if (result && result.type === 'batch_complete' && downloadMode === 'automatic' && sessionZipUrlRef.current && !autoDownloadTriggeredRef.current) {
                // Check if this is the last batch by comparing with total images
                const batchTotal = result.total || 0
                const currentProcessed = processedImages.length
                const totalImages = progress.total || 0
                
                console.log(`[onResult] Batch ${result.batchId} complete: ${batchTotal} images. Current processed: ${currentProcessed}, Total: ${totalImages}`)
                
                // Only trigger auto-download if we've processed all images (or close to it, accounting for async updates)
                // Use a small buffer (5 images) to account for async state updates
                if (currentProcessed >= totalImages - 5 || (batchTotal > 0 && currentProcessed >= totalImages - batchTotal)) {
                  console.log(`[onResult] All batches complete, triggering auto-download for ZIP: ${sessionZipUrlRef.current}`)
                  autoDownloadTriggeredRef.current = true
                  
                  // For large batches, wait longer to ensure ZIP is finalized
                  const delay = totalImages > 300 ? 10000 : (totalImages > 100 ? 5000 : 2000)
                  console.log(`[onResult] Waiting ${delay}ms before downloading ZIP (total images: ${totalImages})`)
                  
                  setTimeout(async () => {
                    try {
                      console.log(`[onResult] Fetching ZIP from: ${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                      const response = await fetch(`${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                      console.log(`[onResult] ZIP fetch response status: ${response.status}`)
                      if (response.ok) {
                        const blob = await response.blob()
                        console.log(`[onResult] ZIP blob size: ${blob.size} bytes`)
                        const url = window.URL.createObjectURL(blob)
                        const link = document.createElement('a')
                        link.href = url
                        link.download = `processed-images-${Date.now()}.zip`
                        document.body.appendChild(link)
                        link.click()
                        document.body.removeChild(link)
                        window.URL.revokeObjectURL(url)
                        console.log(`[onResult] Auto-downloaded ZIP file successfully`)
                      } else {
                        console.error(`[onResult] ZIP download failed with status ${response.status}`)
                        // Retry once after a delay
                        setTimeout(async () => {
                          try {
                            const retryResponse = await fetch(`${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                            if (retryResponse.ok) {
                              const blob = await retryResponse.blob()
                              const url = window.URL.createObjectURL(blob)
                              const link = document.createElement('a')
                              link.href = url
                              link.download = `processed-images-${Date.now()}.zip`
                              document.body.appendChild(link)
                              link.click()
                              document.body.removeChild(link)
                              window.URL.revokeObjectURL(url)
                              console.log(`[onResult] Auto-downloaded ZIP file on retry`)
                            }
                          } catch (retryErr) {
                            console.error('[onResult] ZIP download retry failed:', retryErr)
                          }
                        }, 3000)
                      }
                    } catch (err) {
                      console.error('[onResult] Auto-download failed:', err)
                    }
                  }, delay)
                } else {
                  console.log(`[onResult] Not all batches complete yet (${currentProcessed}/${totalImages}), waiting for more...`)
                }
                return
              }
              
              // Check if this is a processed image result
              if (result && (result.success === true || result.type === 'image_processed')) {
                console.log(`[onResult] Image ${result.taskId} processed: ${result.filename}`)
                console.log(`[onResult] Result has zipUrl: ${!!result.zipUrl}, zipUrl value: ${result.zipUrl}`)
                console.log(`[onResult] Result has sessionId: ${!!result.sessionId}, sessionId value: ${result.sessionId}`)
                
                // Store ZIP URL if provided (for auto-download after all images are processed)
                if (result.zipUrl && !sessionZipUrlRef.current) {
                  sessionZipUrlRef.current = result.zipUrl
                  console.log(`[onResult] Stored session ZIP URL: ${result.zipUrl}`)
                } else if (result.sessionId && !sessionZipUrlRef.current) {
                  // Fallback: construct ZIP URL from sessionId if zipUrl is not provided
                  sessionZipUrlRef.current = `/api/download-progressive-zip?sessionId=${result.sessionId}`
                  console.log(`[onResult] Constructed session ZIP URL from sessionId: ${sessionZipUrlRef.current}`)
                }
                
                try {
                  const imageBlob = await downloadImageFromBackend(result.downloadUrl)
                  
                  // Convert Blob directly to data URL
                  const dataUrl = await new Promise((resolve, reject) => {
                    const reader = new FileReader()
                    reader.onload = () => resolve(reader.result)
                    reader.onerror = () => reject(new Error('Failed to convert blob to data URL'))
                    reader.readAsDataURL(imageBlob)
                  })
                  
                  // Get the original file from fileReferenceMap (set before sending)
                  const fileRef = ws.fileReferenceMap?.get(result.taskId)
                  const task = fileRef ? null : (ws.pendingTasks?.get(result.taskId))
                  const originalFile = fileRef?.file || task?.file || null
                  const originalUrl = fileRef?.originalUrl || (originalFile ? (originalImageUrls.get(originalFile.name) || null) : null)
                  
                  const processedImageData = {
                    file: originalFile,
                    imageId: result.imageId,
                    downloadUrl: result.downloadUrl,
                    format: result.format || fileType,
                    filename: result.filename,
                    originalUrl: originalUrl,
                    processedUrl: dataUrl
                  }
                  
                  // Add to state and update progress
                  setProcessedImages(prev => {
                    const exists = prev.some(img => img.imageId === processedImageData.imageId)
                    console.log(`[onResult] Adding image to state, exists: ${exists}, current count: ${prev.length}`)
                    if (exists) {
                      return prev
                    }
                    const newState = [...prev, processedImageData]
                    console.log(`[onResult] New state count: ${newState.length}`)
                    return newState
                  })
                  
                  // Update progress as each image is processed (separate from setProcessedImages to avoid nested updates)
                  setProgress(prevProgress => {
                    if (prevProgress.total === 0) {
                      return prevProgress // Don't update if total is 0
                    }
                    const newProcessed = Math.min(prevProgress.processed + 1, prevProgress.total) // Cap at total
                    const newPercentage = Math.min(100, Math.round((newProcessed / prevProgress.total) * 100))
                    console.log(`[onResult] Progress update: ${newProcessed}/${prevProgress.total} (${newPercentage}%)`)
                    return {
                      ...prevProgress,
                      processed: newProcessed,
                      percentage: newPercentage
                    }
                  })
                  
                } catch (err) {
                  console.error(`Error processing image ${result.taskId}:`, err)
                  console.error('Error details:', err.stack)
                }
              } else {
                console.log('Result does not match condition - skipping:', result)
              }
            },       
            // onError callback
            (error) => {
              console.error('WebSocket error:', error)
              setError(error.message || 'WebSocket connection error')
            },
            // onClose callback
            () => {
              console.log('WebSocket closed')
              setIsLoading(false)
            }
          )
          
          wsRef.current = ws
          
          // Connect WebSocket with batch size from concurrency setting
          await ws.connect(backgroundColor, fileType, watermark, concurrency)
          
          // Split images into batches based on concurrency setting
          const batchSize = Math.max(1, Math.min(concurrency, 600)) // Clamp between 1 and 600
          const batches = []
          for (let i = 0; i < remainingImages.length; i += batchSize) {
            batches.push(remainingImages.slice(i, i + batchSize))
          }
          
          // Initialize progress with total images and batch count
          setProgress({ 
            processed: 1, 
            total: totalImages, 
            percentage: Math.round((1 / totalImages) * 100), 
            currentBatch: 0, 
            totalBatches: batches.length 
          })
          
          // Pipeline workflow: upload next batch when current batch starts processing
          // Batch 1: Upload → Start Processing
          // Batch 2: Upload (while Batch 1 processes) → Wait for Batch 1 → Start Processing
          // Batch 3: Upload (while Batch 2 processes) → Wait for Batch 2 → Start Processing
          // This keeps GPU always busy
          
          const batchResultsMap = new Map() // Track results by batch ID
          let currentProcessingBatch = null
          
          // Track when batches start processing
          const batchProcessingStarted = new Set()
          
          // Enhanced result callback to track batch processing start
          const originalOnResult = ws.onResult
          
          // Track batch starts by monitoring the original callback
          if (originalOnResult) {
            ws.onResult = (result) => {
              // Call original callback first
              originalOnResult(result)
              // Track when batch starts processing (first result from a batch)
              if (result.taskId !== undefined) {
                const task = ws.pendingTasks?.get(result.taskId)
                if (task && task.batchId !== undefined) {
                  if (!batchProcessingStarted.has(task.batchId)) {
                    batchProcessingStarted.add(task.batchId)
                  }
                }
              }
            }
          }
          
          // Initialize fileReferenceMap on WebSocket instance to store file references
          if (!ws.fileReferenceMap) {
            ws.fileReferenceMap = new Map()
          }
          
          // Process batches in pipeline
          for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
            if (isCancelledRef.current) {
              break
            }
            
            const batch = batches[batchIndex]
            const batchId = batchIndex
            
            setProgress(prev => ({ ...prev, currentBatch: batchId + 1 }))
            
            // Store file references BEFORE sending batch
            const originalSendBatch = ws.sendBatch.bind(ws)
            const batchFileMap = new Map() // file -> { originalUrl }
            
            // Create a wrapper that stores file references
            ws.sendBatch = function(files, batchId) {
              // Store file references for this batch BEFORE calling original
              files.forEach((file) => {
                const originalUrl = originalImageUrls.get(file.name) || null
                batchFileMap.set(file, { originalUrl })
              })
              
              // Call original sendBatch
              const promise = originalSendBatch(files, batchId)
              
              // After sendBatch sets up pendingTasks, copy file references to fileReferenceMap by taskId
              setTimeout(() => {
                files.forEach((file) => {
                  // Find the taskId for this file in pendingTasks
                  for (const [taskId, task] of this.pendingTasks.entries()) {
                    if (task.file === file && task.batchId === batchId) {
                      const fileInfo = batchFileMap.get(file)
                      if (fileInfo && !this.fileReferenceMap.has(taskId)) {
                        this.fileReferenceMap.set(taskId, { 
                          file, 
                          originalUrl: fileInfo.originalUrl 
                        })
                      }
              break
                    }
                  }
                })
              }, 50) // Small delay to ensure pendingTasks are set
              
              return promise
            }
            
            try {
              // Upload batch (this is fast - just sending data)
              const uploadPromise = ws.sendBatch(batch, batchId)
              
              // If this is not the first batch, wait for previous batch to START processing
              // (not finish, just start - pipeline effect)
              if (batchIndex > 0) {
                const prevBatchId = batchIndex - 1
                // Wait a bit for previous batch to start processing
                // The backend will queue this batch and process it after previous batch completes
                await new Promise(resolve => setTimeout(resolve, 100))
              }
              
              // Wait for batch to complete processing
              // Note: Individual images are already displayed via onResult callback above
              // This just waits for the batch promise to resolve for tracking
              const batchResults = await uploadPromise
              
              // Results are already added to allProcessedImagesForDownload via onResult callback
              // This is just for logging and tracking
              
            } catch (err) {
              console.error(`Error processing batch ${batchId}:`, err)
              // Continue with next batch
            }
          }
          
          
          // Update final progress
          setProgress(prev => ({
            ...prev,
            processed: prev.total,
            percentage: 100
          }))
          
          // If automatic download mode and we have a ZIP URL, trigger download after all processing is complete
          // For large batches, wait a bit longer to ensure all images are added to ZIP
          console.log(`[Processing Complete] Checking auto-download: downloadMode=${downloadMode}, hasZipUrl=${!!sessionZipUrlRef.current}, alreadyTriggered=${autoDownloadTriggeredRef.current}, totalImages=${totalImages}`)
          if (downloadMode === 'automatic' && sessionZipUrlRef.current && !autoDownloadTriggeredRef.current) {
            console.log(`[Processing Complete] Triggering auto-download for ZIP: ${sessionZipUrlRef.current}`)
            autoDownloadTriggeredRef.current = true
            
            // For large batches, wait longer to ensure ZIP is finalized
            // Scale delay based on number of images: 2s for <100, 5s for 100-300, 10s for >300
            const delay = totalImages > 300 ? 10000 : (totalImages > 100 ? 5000 : 2000)
            console.log(`[Processing Complete] Waiting ${delay}ms before downloading ZIP (total images: ${totalImages})`)
            
            setTimeout(async () => {
              try {
                console.log(`[Processing Complete] Fetching ZIP from: ${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                const response = await fetch(`${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                console.log(`[Processing Complete] ZIP fetch response status: ${response.status}`)
                if (response.ok) {
                  const blob = await response.blob()
                  console.log(`[Processing Complete] ZIP blob size: ${blob.size} bytes`)
                  const url = window.URL.createObjectURL(blob)
                  const link = document.createElement('a')
                  link.href = url
                  link.download = `processed-images-${Date.now()}.zip`
                  document.body.appendChild(link)
                  link.click()
                  document.body.removeChild(link)
                  window.URL.revokeObjectURL(url)
                  console.log(`[Processing Complete] Auto-downloaded ZIP file successfully`)
                } else {
                  const errorText = await response.text()
                  console.error(`[Processing Complete] Failed to download ZIP: ${response.status} ${response.statusText} - ${errorText}`)
                  // Retry once after a longer delay
                  console.log(`[Processing Complete] Retrying ZIP download after 3 seconds...`)
                  setTimeout(async () => {
                    try {
                      const retryResponse = await fetch(`${API_CONFIG.BASE_URL}${sessionZipUrlRef.current}`)
                      if (retryResponse.ok) {
                        const blob = await retryResponse.blob()
                        const url = window.URL.createObjectURL(blob)
                        const link = document.createElement('a')
                        link.href = url
                        link.download = `processed-images-${Date.now()}.zip`
                        document.body.appendChild(link)
                        link.click()
                        document.body.removeChild(link)
                        window.URL.revokeObjectURL(url)
                        console.log(`[Processing Complete] Auto-downloaded ZIP file successfully on retry`)
                      }
                    } catch (retryErr) {
                      console.error('[Processing Complete] Retry failed:', retryErr)
                    }
                  }, 3000)
                }
              } catch (err) {
                console.error('[Processing Complete] Auto-download failed:', err)
                console.error('[Processing Complete] Error stack:', err.stack)
              }
            }, delay)
          } else if (downloadMode === 'automatic' && !sessionZipUrlRef.current) {
            console.warn(`[Processing Complete] Auto-download mode enabled but no ZIP URL available`)
          }
          
          // Close WebSocket connection
          ws.close()
          wsRef.current = null
          
        } catch (err) {
          if (wsRef.current) {
            wsRef.current.close()
            wsRef.current = null
          }
          
          if (err.name === 'AbortError' || isCancelledRef.current) {
            setIsLoading(false)
            return
          }
          console.error('Error in streaming processing:', err)
          setError(err.message || 'Error processing images')
        }
      } else {
        // Local mode - just use original images
        const localResults = remainingImages.map(file => ({
          file,
          imageId: null,
          downloadUrl: null,
          format: fileType,
          filename: file.name
        }))
        allProcessedImagesForDownload.push(...localResults)
      }

      setIsLoading(false)
      
      console.log(`Processing complete. ${allProcessedImagesForDownload.length} images ready for download.`)
      
      // Download all processed images at the end (manual or automatic)
      if (!isCancelledRef.current && allProcessedImagesForDownload.length > 0) {
        if (downloadMode === 'automatic') {
          // Auto-download all images as ZIP
        setTimeout(async () => {
          try {
              await downloadAllProcessedImagesAsZip(allProcessedImagesForDownload, fileType, watermark, backgroundColor, true)
            } catch (err) {
              console.error('Auto-download failed:', err)
            }
          }, 500)
        } else {
          // Store for manual download (don't display in UI, just store metadata)
          setProcessedImages(allProcessedImagesForDownload)
        }
      }
    }
  }

  // Helper function to download all processed images as ZIP (server-side ZIP creation)
  // Note: isDownloading state should be managed by the caller
  const downloadAllProcessedImagesAsZip = async (imagesToDownload, fileType, watermark, backgroundColor, manageState = false) => {
    if (manageState) {
      setIsDownloading(true)
    }
    try {
      // Collect all image IDs
      const imageIds = []
      for (const item of imagesToDownload) {
        if (item.imageId) {
          imageIds.push(item.imageId)
        } else if (item.downloadUrl) {
          // Extract imageId from downloadUrl if needed
          const match = item.downloadUrl.match(/imageId=([^&]+)/)
          if (match) {
            imageIds.push(match[1])
          }
        }
      }
      
      if (imageIds.length === 0) {
        throw new Error('No valid image IDs found for ZIP download')
      }
      
      console.log(`Downloading ${imageIds.length} images as ZIP from server...`)
      
      // Use server-side ZIP creation for faster downloads
      await downloadImagesAsZip(imageIds)
      
      console.log(`ZIP download completed: ${imageIds.length} images`)
          } catch (err) {
      console.error('Error downloading ZIP file:', err)
      throw err
    } finally {
      if (manageState) {
        setIsDownloading(false)
      }
    }
  }

  const stopProcessing = () => {
    isCancelledRef.current = true
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    // Close WebSocket connection if open
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
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

  const downloadAllProcessedImages = async (fileType, asZip = false, watermark = 'none', backgroundColor = 'white') => {
    const imagesToDownload = []
    
    // Add first image if available (from state)
    if (imageUrl && currentFile && imageId) {
      imagesToDownload.push({
        file: currentFile,
        imageId: imageId,
        downloadUrl: `/api/download?imageId=${imageId}`,
        format: fileType,
        filename: currentFile.name,
        url: imageUrl // Keep for backward compatibility
      })
    }
    
    // Add all processed images (from stored metadata - no processedUrl, just imageId/downloadUrl)
    if (processedImages && processedImages.length > 0) {
      processedImages.forEach(item => {
        imagesToDownload.push({
          file: item.file,
          imageId: item.imageId,
          downloadUrl: item.downloadUrl,
          format: item.format || fileType,
          filename: item.filename || item.file?.name
        })
      })
    }
    
    if (imagesToDownload.length === 0) {
      setError('No processed images to download')
      return
    }
    
    setIsDownloading(true)
    try {
      if (asZip) {
        // Use the optimized ZIP download function
        await downloadAllProcessedImagesAsZip(imagesToDownload, fileType, watermark, backgroundColor)
      } else {
        // Download all images individually in parallel
        console.log(`Downloading ${imagesToDownload.length} images individually...`)
        const downloadPromises = imagesToDownload.map(async (item, i) => {
          try {
            let blob
            if (item.url && item.url.startsWith('data:')) {
              // First image from state (already downloaded)
              blob = dataURLToBlob(item.url)
            } else if (item.downloadUrl || item.imageId) {
              // Download from backend
              blob = await downloadImageFromBackend(item.imageId || item.downloadUrl, item.format || fileType)
              
              // Apply watermark if needed
              if (watermark === 'blog' && blob) {
                const url = URL.createObjectURL(blob)
                const watermarkedUrl = await addWatermark(url, backgroundColor)
                blob = dataURLToBlob(watermarkedUrl)
                URL.revokeObjectURL(url)
              }
            } else {
              throw new Error(`No valid download source for image ${i + 1}`)
            }
            
            const filename = generateDownloadFilename(item.filename || item.file?.name || 'image.png', item.format || fileType)
            downloadFile(blob, filename)
            return { filename, success: true }
          } catch (err) {
            console.error(`Error downloading ${item.filename || item.file?.name}:`, err)
            return { filename: item.filename || item.file?.name, success: false, error: err }
          }
        })
        
        await Promise.all(downloadPromises)
        console.log('All individual downloads completed')
      }
    } catch (err) {
      setError(`Failed to download all images: ${err.message}`)
    } finally {
      setIsDownloading(false)
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
    progress,
    isDownloading,
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

