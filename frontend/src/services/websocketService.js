/**
 * WebSocket service for pipelined batch image processing with streaming results
 */
import { API_CONFIG } from '../config/api'

export class ImageProcessingWebSocket {
  constructor(onResult, onError, onClose) {
    this.ws = null
    this.onResult = onResult
    this.onError = onError
    this.onClose = onClose
    this.isConnected = false
    this.taskCounter = 0
    this.batchQueued = new Set() // Track which batches have started processing
    this.batchUploadComplete = new Set() // Track which batches have finished uploading
    this.batchComplete = new Set() // Track which batches have completed processing
    this.batchFiles = new Map() // {batchId: [file1, file2, ...]} - track files per batch
  }

  connect(backgroundColor, fileType, watermark, batchSize = 100) {
    return new Promise((resolve, reject) => {
      try {
        // Get WebSocket URL
        // In production, use same protocol/host as current page (nginx will proxy)
        // In development, convert http to ws
        let wsUrl
        if (!API_CONFIG.BASE_URL || API_CONFIG.BASE_URL === '') {
          // Production: use current page's protocol and host (nginx proxy)
          const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
          const host = window.location.host
          wsUrl = `${protocol}//${host}/ws/process-images`
        } else {
          // Development: convert http/https to ws/wss
          if (API_CONFIG.BASE_URL.startsWith('https://')) {
            wsUrl = API_CONFIG.BASE_URL.replace(/^https/, 'wss') + '/ws/process-images'
          } else if (API_CONFIG.BASE_URL.startsWith('http://')) {
            wsUrl = API_CONFIG.BASE_URL.replace(/^http/, 'ws') + '/ws/process-images'
          } else {
            wsUrl = API_CONFIG.BASE_URL + '/ws/process-images'
          }
        }
        
        console.log('[WS] Connecting to:', wsUrl, '(baseUrl:', API_CONFIG.BASE_URL, ')')
        
        this.ws = new WebSocket(wsUrl)
        
        this.ws.onopen = () => {
          console.log('[WS] WebSocket connected')
          this.isConnected = true
          
          // Send configuration
          this.ws.send(JSON.stringify({
            type: 'config',
            backgroundColor: backgroundColor || 'white',
            fileType: fileType || 'JPEG',
            watermark: watermark || 'none',
            batchSize: batchSize || 100
          }))
          
          resolve()
        }
        
        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            
            if (data.type === 'config_ack') {
              console.log('[WS] Configuration acknowledged')
            } else if (data.type === 'batch_queued') {
              // Batch processing started - signal to frontend that next batch can upload
              const batchId = data.batchId
              this.batchQueued.add(batchId)
              console.log(`[WS] Received batch_queued for batch ${batchId}`)
              if (this.onResult) {
                this.onResult(data)
              }
            } else if (data.type === 'image_processed') {
              // Individual image processed - send to frontend immediately
              if (this.onResult) {
                this.onResult(data)
              }
            } else if (data.type === 'batch_complete') {
              // Batch processing complete
              this.batchComplete.add(data.batchId)
              if (this.onResult) {
                this.onResult(data)
              }
            } else if (data.type === 'batch_error') {
              if (this.onError) {
                this.onError(new Error(data.error || 'Batch processing failed'))
              }
            } else if (data.type === 'error') {
              if (this.onError) {
                this.onError(new Error(data.message))
              }
            }
          } catch (err) {
            console.error('[WS] Error parsing message:', err)
            if (this.onError) {
              this.onError(err)
            }
          }
        }
        
        this.ws.onerror = (error) => {
          console.error('[WS] WebSocket error:', error)
          console.error('[WS] Failed to connect to:', wsUrl)
          console.error('[WS] This usually means nginx is not configured to proxy WebSocket connections')
          this.isConnected = false
          const errorMsg = new Error(
            `WebSocket connection failed. Please ensure nginx is configured to proxy WebSocket connections to /ws/`
          )
          if (this.onError) {
            this.onError(errorMsg)
          }
          reject(errorMsg)
        }
        
        this.ws.onclose = () => {
          console.log('[WS] WebSocket closed')
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
      
      // Store files for this batch (for mapping taskId to file)
      this.batchFiles.set(batchId, files)
      
      let filesSent = 0
      const totalFiles = files.length
      const batchResults = []
      
      // Send batch start (optional, for tracking)
      // Note: Backend expects batchSize in batch_end, so we'll include it there
      
      // Send all images (taskId is index within batch, 0-based)
      const sendNext = (index) => {
        if (index >= files.length) {
          // All files sent, send batch_end with batchSize
          this.ws.send(JSON.stringify({
            type: 'batch_end',
            batchId: batchId,
            batchSize: totalFiles  // Tell backend how many images to expect
          }))
          this.batchUploadComplete.add(batchId)
          console.log(`[WS] Batch ${batchId} upload complete (${filesSent}/${totalFiles} files)`)
          resolve(batchResults)
          return
        }
        
        const file = files[index]
        const taskId = index  // taskId is index within batch (0-99)
        
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
            
            filesSent++
            
            // Continue with next file
            sendNext(index + 1)
          } catch (err) {
            reject(err)
          }
        }
        reader.onerror = () => {
          reject(new Error(`Failed to read file: ${file.name}`))
        }
        reader.readAsArrayBuffer(file)
      }
      
      // Start sending files
      sendNext(0)
    })
  }
  
  getFileForResult(result) {
    // Get the file corresponding to a result
    const batchId = result.batchId
    const taskId = result.taskId
    const batchFiles = this.batchFiles.get(batchId)
    if (batchFiles && taskId >= 0 && taskId < batchFiles.length) {
      return batchFiles[taskId]
    }
    return null
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
