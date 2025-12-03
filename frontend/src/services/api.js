import { API_CONFIG } from '../config/api'

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
        const baseUrl = API_CONFIG.BASE_URL || 'http://localhost:8000'
        const wsUrl = baseUrl.replace(/^http/, 'ws') + '/ws/process-images'
        
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
              // Batch started/queued
              console.log(`Batch ${data.batchId} ${data.type === 'batch_started' ? 'upload started' : 'queued for processing'}`)
            } else if (data.type === 'batch_complete') {
              // Batch processing complete (all individual results already received)
              console.log(`Batch ${data.batchId} complete: ${data.successful} successful, ${data.failed} failed`)
              // The batch resolve is already called when all individual results are received
            } else if (data.success !== undefined) {
              // Processing result
              const taskId = data.taskId
              if (this.pendingTasks.has(taskId)) {
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
                
                // Call result callback
                if (this.onResult) {
                  this.onResult(data)
                }
              }
            } else if (data.type === 'error') {
              if (this.onError) {
                this.onError(new Error(data.message))
              }
            }
          } catch (err) {
            console.error('Error parsing WebSocket message:', err)
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
      
      // Send batch end (triggers processing) after all files are read
      // Use a small delay to ensure all images are sent
      setTimeout(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({
            type: 'batch_end',
            batchId: batchId
          }))
        }
      }, 200) // Small delay to ensure all images are sent
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
      this.isConnected = false
      this.pendingTasks.clear()
    }
  }
}

/**
 * Upload image to backend for processing
 */
export const uploadImageToBackend = async (file, bgColor, outputFormat, signal = null) => {
  const formData = new FormData()
  formData.append('image', file)
  formData.append('backgroundColor', bgColor)
  formData.append('fileType', outputFormat)
  
  try {
    console.log('Uploading to:', API_CONFIG.UPLOAD_ENDPOINT)
    const fetchOptions = {
      method: 'POST',
      body: formData
    }
    
    if (signal) {
      fetchOptions.signal = signal
    }
    
    const response = await fetch(API_CONFIG.UPLOAD_ENDPOINT, fetchOptions)
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(errorData.detail || `Upload failed with status ${response.status}`)
    }
    
    const data = await response.json()
    return {
      imageUrl: data.imageUrl,
      imageId: data.imageId
    }
  } catch (error) {
    // Handle abort error
    if (error.name === 'AbortError') {
      throw error
    }
    // More detailed error message
    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
      throw new Error(`Cannot connect to backend. Make sure the backend is running on ${API_CONFIG.BASE_URL || 'http://localhost:8000'}`)
    }
    throw new Error(`Upload failed: ${error.message}`)
  }
}

/**
 * Upload multiple images to backend for batch processing
 */
export const uploadImagesBatchToBackend = async (files, bgColor, outputFormat, signal = null) => {
  const formData = new FormData()
  
  // Append all images with the same field name "images"
  files.forEach(file => {
    formData.append('images', file)
  })
  
  formData.append('backgroundColor', bgColor)
  formData.append('fileType', outputFormat)
  
  try {
    console.log(`Uploading batch of ${files.length} images to:`, `${API_CONFIG.BASE_URL}/api/upload-batch`)
    const fetchOptions = {
      method: 'POST',
      body: formData
    }
    
    if (signal) {
      fetchOptions.signal = signal
    }
    
    const response = await fetch(`${API_CONFIG.BASE_URL}/api/upload-batch`, fetchOptions)
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Batch upload failed' }))
      throw new Error(errorData.detail || `Batch upload failed with status ${response.status}`)
    }
    
    const data = await response.json()
    return {
      results: data.results,
      total: data.total,
      successful: data.successful,
      failed: data.failed
    }
  } catch (error) {
    // Handle abort error
    if (error.name === 'AbortError') {
      throw error
    }
    // More detailed error message
    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
      throw new Error(`Cannot connect to backend. Make sure the backend is running on ${API_CONFIG.BASE_URL || 'http://localhost:8000'}`)
    }
    throw new Error(`Batch upload failed: ${error.message}`)
  }
}

/**
 * Download processed image from backend
 * Supports both imageId and direct downloadUrl
 */
export const downloadImageFromBackend = async (imageIdOrUrl, outputFormat = null) => {
  try {
    let url
    if (imageIdOrUrl.startsWith('/api/download') || imageIdOrUrl.startsWith('http')) {
      // It's already a download URL
      url = imageIdOrUrl.startsWith('http') ? imageIdOrUrl : `${API_CONFIG.BASE_URL}${imageIdOrUrl}`
    } else {
      // It's an imageId, construct URL
      url = `${API_CONFIG.DOWNLOAD_ENDPOINT}?imageId=${encodeURIComponent(imageIdOrUrl)}`
      if (outputFormat) {
        url += `&fileType=${encodeURIComponent(outputFormat)}`
      }
    }
    
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`Download failed with status ${response.status}`)
    }
    const blob = await response.blob()
    return blob
  } catch (error) {
    throw new Error(`Download failed: ${error.message}`)
  }
}

