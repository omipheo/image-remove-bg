import { API_CONFIG } from '../config/api'

/**
 * Upload single image to backend
 */
export const uploadImageToBackend = async (file, backgroundColor, fileType, signal) => {
  const formData = new FormData()
  formData.append('image', file)  // Backend expects 'image' field name
  formData.append('backgroundColor', backgroundColor)
  formData.append('fileType', fileType)

  const response = await fetch(`${API_CONFIG.BASE_URL}/api/upload`, {
    method: 'POST',
    body: formData,
    signal
  })

  if (!response.ok) {
    throw new Error(`Upload failed: ${response.statusText}`)
  }

  const result = await response.json()
  return {
    imageId: result.imageId,
    imageUrl: result.imageUrl || `${API_CONFIG.BASE_URL}${result.downloadUrl}`,
    downloadUrl: result.downloadUrl
  }
}

/**
 * Download image from backend
 */
export const downloadImageFromBackend = async (imageIdOrUrl, fileType) => {
  let url
  if (imageIdOrUrl.startsWith('http') || imageIdOrUrl.startsWith('/')) {
    url = imageIdOrUrl.startsWith('/') ? `${API_CONFIG.BASE_URL}${imageIdOrUrl}` : imageIdOrUrl
  } else {
    url = `${API_CONFIG.BASE_URL}/api/download?imageId=${imageIdOrUrl}`
  }

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Download failed: ${response.statusText}`)
  }
  return await response.blob()
}

/**
 * Download multiple images as ZIP from backend (server-side ZIP creation)
 */
export const downloadImagesAsZip = async (imageIds) => {
  const imageIdsParam = Array.isArray(imageIds) ? imageIds.join(',') : imageIds
  const response = await fetch(`${API_CONFIG.BASE_URL}/api/download-zip?imageIds=${encodeURIComponent(imageIdsParam)}`)
  
  if (!response.ok) {
    throw new Error(`Failed to download ZIP: ${response.statusText}`)
  }
  
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `processed-images-${Date.now()}.zip`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

/**
 * Upload batch of images to backend (legacy, now uses WebSocket)
 */
export const uploadImagesBatchToBackend = async (files, backgroundColor, fileType, watermark) => {
  // This is a legacy function - batch processing now uses WebSocket
  // Keeping for backward compatibility
  throw new Error('Batch upload now uses WebSocket. Use ImageProcessingWebSocket instead.')
}

/**
 * WebSocket service for continuous streaming image processing
 */
export class ImageProcessingWebSocket {
  constructor(onResult, onError, onClose) {
    this.ws = null
    this.onResult = onResult
    this.onError = onError
    this.onClose = onClose
    this.isConnected = false
    this.taskCounter = 0
    this.pendingTasks = new Map() // Track pending tasks: {taskId: {file, resolve, reject}}
    this.batchTrackers = new Map() // Track batch completion: {batchId: {total, completed, results}}
  }

  connect(backgroundColor, fileType, watermark, batchSize = 20) {
    return new Promise((resolve, reject) => {
      try {
        // Get WebSocket URL (convert http to ws, https to wss)
        // In production, use the current page's protocol and host
        let baseUrl = API_CONFIG.BASE_URL
        if (!baseUrl || baseUrl === '') {
          // Production: use current page protocol and host
          const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
          const host = window.location.host
          baseUrl = `${protocol}//${host}`
        } else {
          // Development: convert http/https to ws/wss
          baseUrl = baseUrl.replace(/^http/, 'ws')
        }
        const wsUrl = baseUrl + '/ws/process-images'
        
        this.ws = new WebSocket(wsUrl)
        
        this.ws.onopen = () => {
          console.log('WebSocket connected')
          this.isConnected = true
          
          // Send configuration with batch size
          this.ws.send(JSON.stringify({
            backgroundColor: backgroundColor || 'white',
            fileType: fileType || 'JPEG',
            watermark: watermark || 'none',
            batchSize: batchSize || 20
          }))
          
          resolve()
        }
        
        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            
            if (data.type === 'queued' || data.type === 'image_received') {
              // Image queued/received
              const taskId = data.taskId
              if (this.pendingTasks.has(taskId)) {
                const task = this.pendingTasks.get(taskId)
                task.status = 'queued'
              }
            } else if (data.type === 'batch_started' || data.type === 'batch_queued') {
              // Forward batch events so pipeline can track queue/start
              if (this.onResult) {
                try {
                  this.onResult(data)
                } catch (err) {
                  console.error('Error in onResult callback for batch_started/batch_queued:', err)
                }
              }
            } else if (data.type === 'batch_complete') {
              // Batch processing complete (all individual results already received)
              // Send batch_complete to onResult callback for auto-download trigger
              if (this.onResult) {
                try {
                  this.onResult(data)
                } catch (err) {
                  console.error('Error in onResult callback for batch_complete:', err)
                }
              }
            } else if (data.type === 'image_processed' || data.success !== undefined) {
              // Processing result - send immediately to onResult callback for real-time display
              if (this.onResult) {
                try {
                  this.onResult(data)
                } catch (err) {
                  console.error('Error in onResult callback:', err)
                }
              }
              
              // Also handle task resolution for batch completion tracking
              const taskId = data.taskId
              if (taskId !== undefined && this.pendingTasks.has(taskId)) {
                const task = this.pendingTasks.get(taskId)
                
                if (data.success) {
                  // Success - resolve with result
                  const result = {
                    imageId: data.imageId,
                    downloadUrl: data.downloadUrl,
                    filename: data.filename,
                    format: data.format,
                    mimeType: data.mimeType
                  }
                  
                  // If task has a resolve function (from sendBatch), call it
                  if (typeof task.resolve === 'function') {
                    task.resolve(result)
                  }
                  
                  // For single image sends, delete from pending
                  if (!task.batchId) {
                    this.pendingTasks.delete(taskId)
                  }
                } else {
                  // Error - reject
                  if (typeof task.reject === 'function') {
                    task.reject(new Error(data.error || 'Processing failed'))
                  }
                  if (!task.batchId) {
                    this.pendingTasks.delete(taskId)
                  }
                }
              }
            } else if (data.type === 'error') {
              if (this.onError) {
                this.onError(new Error(data.message))
              }
            } else {
              // Unknown message type - log warning
              console.warn('[WebSocket] Unknown message type:', data.type)
            }
          } catch (err) {
            console.error('Error parsing WebSocket message:', err)
            console.error('Raw event.data:', event.data)
            if (this.onError) {
              this.onError(err)
            }
          }
        }
        
        this.ws.onerror = (error) => {
          console.error('WebSocket error:', error)
          this.isConnected = false
          if (this.onError) {
            this.onError(error)
          }
          reject(error)
        }
        
        this.ws.onclose = () => {
          console.log('WebSocket closed')
          this.isConnected = false
          if (this.onClose) {
            this.onClose()
          }
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  sendBatch(files, batchId) {
    return new Promise((resolve, reject) => {
      if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }
      
      const batchResults = new Array(files.length).fill(null)
      let completed = 0
      let hasError = false
      let filesSent = 0
      const totalFiles = files.length
      const batchResolve = resolve
      const batchReject = reject
      
      // Track batch completion
      const batchTracker = {
        batchId: batchId,
        total: files.length,
        completed: 0,
        results: batchResults,
        resolve: batchResolve,
        reject: batchReject
      }
      
      // Store batch tracker
      if (!this.batchTrackers) {
        this.batchTrackers = new Map()
      }
      this.batchTrackers.set(batchId, batchTracker)
      
      // Send batch start
      this.ws.send(JSON.stringify({
        type: 'batch_start',
        batchId: batchId,
        batchSize: files.length
      }))
      
      // Send all images in batch
      files.forEach((file, index) => {
        const taskId = this.taskCounter++
        this.pendingTasks.set(taskId, { 
          file, 
          batchId: batchId,
          batchIndex: index,
          resolve: (result) => {
            batchResults[index] = result
            batchTracker.completed++
            // Check if batch is complete
            if (batchTracker.completed >= batchTracker.total && !hasError) {
              this.batchTrackers.delete(batchId)
              batchResolve(batchResults.filter(r => r !== null))
            }
          }, 
          reject: (error) => {
            if (!hasError) {
              hasError = true
              this.batchTrackers.delete(batchId)
              batchReject(error)
            }
          }, 
          status: 'pending'
        })
        
        // Store file reference in a separate map that won't be cleaned up
        // This is accessible via this.fileReferenceMap from the hook
        if (!this.fileReferenceMap) {
          this.fileReferenceMap = new Map()
        }
        // We'll set this after we have the originalUrl from the hook
        
        // Read file and send
        const reader = new FileReader()
        reader.onload = () => {
          try {
            // Send metadata
            this.ws.send(JSON.stringify({
              type: 'image_metadata',
              filename: file.name,
              taskId: taskId
            }))
            
            // Send binary data
            this.ws.send(reader.result)
            
            // Track that this file has been sent
            filesSent++
            
            // When all files are sent, send batch_end
            if (filesSent >= totalFiles) {
              setTimeout(() => {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                  this.ws.send(JSON.stringify({
                    type: 'batch_end',
                    batchId: batchId
                  }))
                }
              }, 100) // Small delay to ensure all WebSocket messages are queued
            }
          } catch (err) {
            this.pendingTasks.delete(taskId)
            if (!hasError) {
              hasError = true
              this.batchTrackers.delete(batchId)
              batchReject(err)
            }
          }
        }
        reader.onerror = () => {
          this.pendingTasks.delete(taskId)
          if (!hasError) {
            hasError = true
            this.batchTrackers.delete(batchId)
            batchReject(new Error(`Failed to read file: ${file.name}`))
          }
        }
        reader.readAsArrayBuffer(file)
      })
      
      // Fallback: Send batch_end after a longer delay if not all files sent
      // This handles edge cases where FileReader might fail silently
      setTimeout(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN && filesSent < totalFiles) {
          console.warn(`Batch ${batchId}: Only ${filesSent}/${totalFiles} files sent, sending batch_end anyway`)
          this.ws.send(JSON.stringify({
            type: 'batch_end',
            batchId: batchId
          }))
        }
      }, Math.max(10000, totalFiles * 100)) // Dynamic delay: 100ms per file, minimum 10 seconds
    })
  }

  sendImage(file) {
    return new Promise((resolve, reject) => {
      if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'))
        return
      }
      
      const taskId = this.taskCounter++
      this.pendingTasks.set(taskId, { file, resolve, reject, status: 'pending' })
      
      // Read file as ArrayBuffer and send as binary
      const reader = new FileReader()
      reader.onload = () => {
        try {
          // Send metadata first (backend expects this format)
          const metadata = {
            type: 'image_metadata',
            filename: file.name,
            taskId: taskId
          }
          
          // Send metadata as JSON
          this.ws.send(JSON.stringify(metadata))
          
          // Send binary image data immediately after
          this.ws.send(reader.result)
        } catch (err) {
          this.pendingTasks.delete(taskId)
          reject(err)
        }
      }
      reader.onerror = () => {
        this.pendingTasks.delete(taskId)
        reject(new Error('Failed to read file'))
      }
      reader.readAsArrayBuffer(file)
    })
  }

  updateConfig(backgroundColor, fileType, watermark) {
    if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return
    }
    
    this.ws.send(JSON.stringify({
      type: 'config',
      backgroundColor: backgroundColor || 'white',
      fileType: fileType || 'JPEG',
      watermark: watermark || 'none'
    }))
  }

  close() {
    if (this.ws) {
      this.ws.send(JSON.stringify({ type: 'close' }))
      this.ws.close()
      this.ws = null
    }
    this.isConnected = false
  }
}
