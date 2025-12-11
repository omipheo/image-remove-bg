import { useState, useRef } from 'react'
import JSZip from 'jszip'
import { ImageProcessingWebSocket } from '../services/websocketService'
import {
  readImageAsDataURL,
  downloadFile,
  generateDownloadFilename,
  dataURLToBlob
} from '../utils/fileUtils'
import { API_CONFIG } from '../config/api'

// Helper to create ZIP from processed images (fallback)
const createZipFromProcessedImages = async (processedImages) => {
  const zip = new JSZip()
  for (const item of processedImages) {
    try {
      const blob = await fetch(item.processedUrl).then(r => r.blob())
      zip.file(item.file.name, blob)
    } catch (err) {
      console.warn(`[ZIP] Failed to add ${item.file.name} to ZIP:`, err)
    }
  }
  const zipBlob = await zip.generateAsync({ type: 'blob' })
  const filename = `processed-images-${new Date().toISOString().split('T')[0]}.zip`
  downloadFile(zipBlob, filename)
  return { downloadUrl: null, filename }
}

export const useImageProcessing = () => {
  /** ------------------------
   * STATE
   * ------------------------ */
  const [imageUrl, setImageUrl] = useState(null)
  const [originalImageUrl, setOriginalImageUrl] = useState(null)
  const [currentFile, setCurrentFile] = useState(null)
  const [processedImages, setProcessedImages] = useState([])
  const [zipInfo, setZipInfo] = useState(null)

  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const wsRef = useRef(null)
  const abortRef = useRef(false)

  /** ------------------------
   * SINGLE IMAGE
   * ------------------------ */
  const processImage = async (
    file,
    backgroundColor,
    fileType,
    watermark,
    downloadMode
  ) => {
    abortRef.current = false
    setError(null)
    setIsLoading(true)
    setProcessedImages([])
    setZipInfo(null)

    try {
      setCurrentFile(file)

      const originalUrl = await readImageAsDataURL(file)
      setOriginalImageUrl(originalUrl)

      const formData = new FormData()
      formData.append('image', file)
      formData.append('backgroundColor', backgroundColor)
      formData.append('fileType', fileType)
      formData.append('watermark', watermark)

      const res = await fetch(`${API_CONFIG.BASE_URL}/api/upload`, {
        method: 'POST',
        body: formData
      })

      if (!res.ok) throw new Error('Image upload failed')

      const blob = await res.blob()
      const processedUrl = URL.createObjectURL(blob)

      setImageUrl(processedUrl)
      setIsLoading(false)

      if (downloadMode === 'automatic') {
        const filename = generateDownloadFilename(file.name, fileType)
        downloadFile(blob, filename)
      }
    } catch (err) {
      if (!abortRef.current) {
        setError(err.message)
        setIsLoading(false)
      }
    }
  }

  /** ------------------------
   * MULTIPLE IMAGES (WS)
   * ------------------------ */
  const processMultipleImages = async (
    files,
    backgroundColor,
    fileType,
    watermark,
    downloadMode
  ) => {
    abortRef.current = false
    setError(null)
    setIsLoading(true)
    setProcessedImages([])
    setZipInfo(null)

    const originalUrls = new Map()

    for (const file of files) {
      const url = await readImageAsDataURL(file)
      originalUrls.set(file, url)
    }

    // Track batches for ZIP download
    const totalBatches = Math.ceil(files.length / 20)
    const completedBatches = new Set()
    let allBatchesComplete = false

    const ws = new ImageProcessingWebSocket(
      async (msg) => {
        // IMAGE RESULT
        if (msg.type === 'image_processed' && msg.success) {
          const fullUrl = msg.downloadUrl.startsWith('http')
            ? msg.downloadUrl
            : `${API_CONFIG.BASE_URL}${msg.downloadUrl}`

          const res = await fetch(fullUrl)
          const blob = await res.blob()
          const processedUrl = URL.createObjectURL(blob)

          const file = ws.getFileForResult(msg)
          if (!file) return

          setProcessedImages(prev => [
            ...prev,
            {
              file,
              imageId: msg.imageId,
              originalUrl: originalUrls.get(file),
              processedUrl
            }
          ])
        }

        // BATCH COMPLETE - Track completion
        if (msg.type === 'batch_complete') {
          const batchId = msg.batchId
          completedBatches.add(batchId)
          console.log(`[BATCH] Batch ${batchId} complete (${completedBatches.size}/${totalBatches} batches done)`)

          // Check if ALL batches are complete
          if (completedBatches.size >= totalBatches && !allBatchesComplete) {
            allBatchesComplete = true
            console.log('[BATCH] ✅ All batches complete! Creating ZIP...')
            setIsLoading(false)

            // Create ZIP for all processed images
            try {
              // Request ZIP creation from backend
              const zipResponse = await fetch(`${API_CONFIG.BASE_URL}/api/create-zip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batchIds: Array.from(completedBatches) })
              })

              if (zipResponse.ok) {
                const zipData = await zipResponse.json()
                const zipUrl = zipData.downloadUrl.startsWith('http')
                  ? zipData.downloadUrl
                  : `${API_CONFIG.BASE_URL}${zipData.downloadUrl}`

                setZipInfo({
                  downloadUrl: zipUrl,
                  filename: `processed-images-${new Date().toISOString().split('T')[0]}.zip`
                })

                if (downloadMode === 'automatic') {
                  console.log('[ZIP] Auto-download triggered, fetching:', zipUrl)
                  const res = await fetch(zipUrl)
                  if (!res.ok) {
                    throw new Error(`Failed to download ZIP: ${res.status} ${res.statusText}`)
                  }
                  const blob = await res.blob()
                  downloadFile(blob, `processed-images-${new Date().toISOString().split('T')[0]}.zip`)
                  console.log('[ZIP] ✅ Auto-download completed')
                } else {
                  console.log('[ZIP] Manual download mode - ZIP ready at:', zipUrl)
                }
              } else {
                // Fallback: create ZIP from all processed images using state getter
                console.warn('[ZIP] Backend ZIP creation failed, using fallback')
                setProcessedImages(current => {
                  // Use current state value
                  createZipFromProcessedImages(current).then(() => {
                    console.log('[ZIP] ✅ Fallback ZIP downloaded')
                  }).catch(fallbackErr => {
                    console.error('[ZIP] ❌ Fallback ZIP creation failed:', fallbackErr)
                  })
                  return current // Don't modify state
                })
              }
            } catch (err) {
              console.error('[ZIP] ❌ ZIP creation/download failed:', err)
              // Fallback: create ZIP from processed images
              setProcessedImages(current => {
                createZipFromProcessedImages(current).then(() => {
                  console.log('[ZIP] ✅ Fallback ZIP downloaded')
                }).catch(fallbackErr => {
                  console.error('[ZIP] ❌ Fallback ZIP creation also failed:', fallbackErr)
                })
                return current // Don't modify state
              })
            }
          }
        }
      },
      (err) => {
        setError(err.message)
        setIsLoading(false)
      },
      () => {
        setIsLoading(false)
      }
    )

    wsRef.current = ws

    await ws.connect(backgroundColor, fileType, watermark)

    const BATCH_SIZE = 20
    let batchId = 0

    for (let i = 0; i < files.length; i += BATCH_SIZE) {
      const batch = files.slice(i, i + BATCH_SIZE)
      await ws.sendBatch(batch, batchId++)
    }
  }

  /** ------------------------
   * DOWNLOAD HELPERS
   * ------------------------ */
  const downloadImage = (fileType) => {
    if (!imageUrl || !currentFile) return
    const blob = dataURLToBlob(imageUrl)
    downloadFile(blob, generateDownloadFilename(currentFile.name, fileType))
  }

  const downloadProcessedImage = (item, fileType) => {
    const blob = dataURLToBlob(item.processedUrl)
    downloadFile(blob, generateDownloadFilename(item.file.name, fileType))
  }

  const downloadAllProcessedImages = async (fileType, asZip) => {
    if (asZip && zipInfo) {
      const url = zipInfo.downloadUrl.startsWith('http')
        ? zipInfo.downloadUrl
        : `${API_CONFIG.BASE_URL}${zipInfo.downloadUrl}`
      const res = await fetch(url)
      const blob = await res.blob()
      downloadFile(blob, zipInfo.filename)
      return
    }

    for (const item of processedImages) {
      const blob = dataURLToBlob(item.processedUrl)
      downloadFile(blob, generateDownloadFilename(item.file.name, fileType))
      await new Promise(r => setTimeout(r, 150))
    }
  }

  /** ------------------------
   * STOP / RESET
   * ------------------------ */
  const stopProcessing = () => {
    abortRef.current = true
    wsRef.current?.close()
    setIsLoading(false)
  }

  const reset = () => {
    setImageUrl(null)
    setOriginalImageUrl(null)
    setCurrentFile(null)
    setProcessedImages([])
    setZipInfo(null)
    setError(null)
  }

  return {
    imageUrl,
    originalImageUrl,
    currentFile,
    processedImages,
    zipInfo,
    isLoading,
    error,

    processImage,
    processMultipleImages,

    downloadImage,
    downloadProcessedImage,
    downloadAllProcessedImages,

    stopProcessing,
    reset,
    setError
  }
}
