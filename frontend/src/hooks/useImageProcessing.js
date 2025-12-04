import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { uploadImageToBackend, uploadImagesBatchToBackend, downloadImageFromBackend, ImageProcessingWebSocket } from '../services/api'
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
  const abortControllerRef = useRef(null)
  const isCancelledRef = useRef(false)
  const wsRef = useRef(null) // WebSocket reference for streaming

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
      
      // Get remaining images (skip first one as it's already processed and displayed)
      const remainingImages = imageFiles.slice(1)
      
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
            // onResult callback - called when each image is processed
            (result) => {
              if (result.success) {
                console.log(`Image ${result.taskId} processed: ${result.filename}`)
                // Update progress
                setProgress(prev => {
                  const newProcessed = prev.processed + 1
                  return {
                    ...prev,
                    processed: newProcessed,
                    percentage: Math.round((newProcessed / prev.total) * 100)
                  }
                })
              } else {
                console.error(`Image ${result.taskId} failed: ${result.error}`)
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
          
          console.log(`Starting batch-based pipeline processing of ${remainingImages.length} images (batch size: ${concurrency})...`)
          
          // Split images into batches based on concurrency setting
          const batchSize = Math.max(1, Math.min(concurrency, 600)) // Clamp between 1 and 600
          const batches = []
          for (let i = 0; i < remainingImages.length; i += batchSize) {
            batches.push(remainingImages.slice(i, i + batchSize))
          }
          
          console.log(`Split into ${batches.length} batch(es) of ~${batchSize} images each`)
          
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
          ws.onResult = (result) => {
            if (originalOnResult) {
              originalOnResult(result)
            }
            // Track when batch starts processing (first result from a batch)
            if (result.taskId !== undefined) {
              const task = ws.pendingTasks?.get(result.taskId)
              if (task && task.batchId !== undefined) {
                if (!batchProcessingStarted.has(task.batchId)) {
                  batchProcessingStarted.add(task.batchId)
                  console.log(`Batch ${task.batchId} started processing`)
                }
              }
            }
          }
          
          // Process batches in pipeline
          for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
            if (isCancelledRef.current) {
              break
            }
            
            const batch = batches[batchIndex]
            const batchId = batchIndex
            
            console.log(`Uploading batch ${batchId} (${batch.length} images)...`)
            setProgress(prev => ({ ...prev, currentBatch: batchId + 1 }))
            
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
              const batchResults = await uploadPromise
              
              // Store results
              batchResults.forEach((result, idx) => {
                if (result) {
                  allProcessedImagesForDownload.push({
                    file: batch[idx],
                    imageId: result.imageId,
                    downloadUrl: result.downloadUrl,
                    format: result.format || fileType,
                    filename: result.filename
                  })
                }
              })
              
              console.log(`Batch ${batchId} complete. Total: ${allProcessedImagesForDownload.length}/${remainingImages.length}`)
              
            } catch (err) {
              console.error(`Error processing batch ${batchId}:`, err)
              // Continue with next batch
            }
          }
          
          console.log(`Processing complete. ${allProcessedImagesForDownload.length} images ready for download.`)
          
          // Update final progress
          setProgress(prev => ({
            ...prev,
            processed: prev.total,
            percentage: 100
          }))
          
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
              console.log(`Auto-downloading ${allProcessedImagesForDownload.length} processed images...`)
              await downloadAllProcessedImagesAsZip(allProcessedImagesForDownload, fileType, watermark, backgroundColor)
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

  // Helper function to download all processed images as ZIP
  const downloadAllProcessedImagesAsZip = async (imagesToDownload, fileType, watermark, backgroundColor) => {
    try {
      const zip = new JSZip()
      const downloadPromises = []
      
      console.log(`Downloading ${imagesToDownload.length} images in parallel...`)
      
      // Download all images in parallel
      for (const item of imagesToDownload) {
        if (!item.downloadUrl && !item.imageId) {
          continue // Skip items without download info
        }
        
        const downloadPromise = (async () => {
          try {
            let blob
            if (item.downloadUrl || item.imageId) {
              // Download from backend
              blob = await downloadImageFromBackend(item.imageId || item.downloadUrl, item.format || fileType)
            } else {
              return null
            }
            
            // Apply watermark if needed
            if (watermark === 'blog' && blob) {
              const url = URL.createObjectURL(blob)
              const watermarkedUrl = await addWatermark(url, backgroundColor)
              blob = dataURLToBlob(watermarkedUrl)
              URL.revokeObjectURL(url)
            }
            
            const filename = generateDownloadFilename(item.filename || item.file?.name || 'image.png', item.format || fileType)
            zip.file(filename, blob)
            return { filename, success: true }
          } catch (err) {
            console.error(`Error downloading ${item.filename || item.file?.name}:`, err)
            return { filename: item.filename || item.file?.name, success: false, error: err }
          }
        })()
        
        downloadPromises.push(downloadPromise)
      }
      
      // Wait for all downloads to complete
      await Promise.all(downloadPromises)
      
      // Generate and download ZIP
      if (Object.keys(zip.files).length > 0) {
        const zipBlob = await zip.generateAsync({ 
          type: 'blob',
          compression: 'DEFLATE',
          compressionOptions: { level: 6 }
        })
        const zipFilename = `processed-images-${Date.now()}.zip`
        downloadFile(zipBlob, zipFilename)
        console.log(`Auto-download ZIP triggered: ${zipFilename} (${Object.keys(zip.files).length} images)`)
      }
    } catch (err) {
      console.error('Error creating ZIP file:', err)
      throw err
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

