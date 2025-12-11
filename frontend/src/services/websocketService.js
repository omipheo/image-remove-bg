/**
 * OPTIMIZED WebSocket Service for Fast Image Uploads
 * OPTIMIZED FOR 4x RTX 3090 + 600 Mbps Upload
 */

import { API_CONFIG } from '../config/api'

export class ImageProcessingWebSocket {
  constructor(onResult, onError, onClose) {
    this.ws = null
    this.onResult = onResult
    this.onError = onError
    this.onClose = onClose
    this.isConnected = false
    this.batchQueued = new Set()
    this.batchComplete = new Set()
    this.batchFiles = new Map()
    // Map (batchId, taskId) -> file for reliable lookup
    this.fileMap = new Map()

    // OPTIMIZATION: Increased for 600 Mbps upload speed
    // this.maxConcurrentUploads = 20  // Increased from 10 to 20
    // this.chunkSize = 512 * 1024     // Increased from 256KB to 512KB
    // this.maxBufferSize = 2048 * 1024 // Increased from 1MB to 2MB
  }

  connect(backgroundColor, fileType, watermark, batchSize = 20) {
    return new Promise((resolve, reject) => {
      try {
        let wsUrl
        if (!API_CONFIG.BASE_URL || API_CONFIG.BASE_URL === '') {
          const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
          const host = window.location.host
          wsUrl = `${protocol}//${host}/ws/process-images`
        } else {
          if (API_CONFIG.BASE_URL.startsWith('https://')) {
            wsUrl = API_CONFIG.BASE_URL.replace(/^https/, 'wss') + '/ws/process-images'
          } else if (API_CONFIG.BASE_URL.startsWith('http://')) {
            wsUrl = API_CONFIG.BASE_URL.replace(/^http/, 'ws') + '/ws/process-images'
          } else {
            wsUrl = API_CONFIG.BASE_URL + '/ws/process-images'
          }
        }

        console.log('[WS] Connecting to:', wsUrl)
        this.ws = new WebSocket(wsUrl)
        // this.ws.binaryType = 'arraybuffer'

        this.ws.onopen = () => {
          console.log('[WS] ✅ WebSocket connected')
          this.isConnected = true

          this.ws.send(JSON.stringify({
            type: 'config',
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

            if (data.type === 'config_ack') {
              console.log('[WS] Configuration acknowledged')
            } else if (data.type === 'batch_queued') {
              const batchId = data.batchId
              this.batchQueued.add(batchId)
              console.log(`[WS] 🚀 Batch ${batchId} queued - GPU processing started`)
              if (this.onResult) this.onResult(data)
            } else if (data.type === 'image_processed') {
              if (this.onResult) this.onResult(data)
            } else if (data.type === 'batch_complete') {
              this.batchComplete.add(data.batchId)
              console.log(`[WS] ✅ Batch ${data.batchId} complete`)
              if (this.onResult) this.onResult(data)
            } else if (data.type === 'batch_error' || data.type === 'error') {
              console.error('[WS] ❌ Error:', data.error || data.message)
              if (this.onError) {
                this.onError(new Error(data.error || data.message || 'Processing error'))
              }
            }
          } catch (err) {
            console.error('[WS] Error parsing message:', err)
            if (this.onError) this.onError(err)
          }
        }

        this.ws.onerror = (error) => {
          console.error('[WS] ❌ WebSocket error:', error)
          this.isConnected = false
          const errorMsg = new Error('WebSocket connection failed')
          if (this.onError) this.onError(errorMsg)
          reject(errorMsg)
        }

        this.ws.onclose = () => {
          console.log('[WS] WebSocket closed')
          this.isConnected = false
          if (this.onClose) this.onClose()
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  async sendBatch(files, batchId) {
    if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected')
    }

    console.log(`[WS] 📤 Starting upload for batch ${batchId} (${files.length} files)`)
    const startTime = performance.now()

    this.batchFiles.set(batchId, files)

    // Build file mapping for reliable lookup
    files.forEach((file, index) => {
      const key = `${batchId}_${index}`
      this.fileMap.set(key, file)
      console.log(`[WS] Mapped batchId=${batchId}, taskId=${index} -> ${file.name}`)
    })

    // Convert all files to base64
    // const imageDataList = await Promise.all(
    //   files.map(async (file, index) => {
    //     const arrayBuffer = await file.arrayBuffer()
    //     const base64 = this._arrayBufferToBase64(arrayBuffer)

    //     return {
    //       taskId: index,
    //       filename: file.name,
    //       data: base64,
    //       size: file.size
    //     }
    //   })
    // )
    const imageDataList = [];

    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      const arrayBuffer = await file.arrayBuffer();
      const base64 = this._arrayBufferToBase64(arrayBuffer);

      imageDataList.push({
        taskId: index,
        filename: file.name,
        data: base64,
        size: file.size
      });
    }


    const conversionTime = ((performance.now() - startTime) / 1000).toFixed(2)
    console.log(`[WS] ✅ Converted ${files.length} files in ${conversionTime}s`)

    console.log(`[WS] 📤 Sending batch ${batchId} (${files.length} images)...`)
    const sendStart = performance.now()

    const batchPayload = {
      type: 'batch_images',
      batchId: batchId,
      batchSize: files.length,
      images: imageDataList
    }

    this.ws.send(JSON.stringify(batchPayload))

    const sendTime = ((performance.now() - sendStart) / 1000).toFixed(2)
    const totalTime = ((performance.now() - startTime) / 1000).toFixed(2)
    const throughput = (files.length / totalTime).toFixed(1)

    console.log(`[WS] ✅ Batch ${batchId} sent in ${sendTime}s (total: ${totalTime}s, ${throughput} files/sec)`)

    // await this._uploadFilesParallel(files, batchId)

    // // CRITICAL: Wait for buffer to drain
    // console.log(`[WS] Waiting for buffer to drain (current: ${this.ws.bufferedAmount} bytes)...`)
    // await this._waitForBufferDrain()

    // // Additional safety delay
    // await new Promise(resolve => setTimeout(resolve, 300))  // Reduced from 500ms to 300ms

    // this.ws.send(JSON.stringify({
    //   type: 'batch_end',
    //   batchId: batchId,
    //   batchSize: files.length
    // }))

    // this.batchUploadComplete.add(batchId)

    // const elapsed = ((performance.now() - startTime) / 1000).toFixed(2)
    // const throughput = (files.length / elapsed).toFixed(1)
    // const mbps = ((files.reduce((sum, f) => sum + f.size, 0) * 8 / 1000000) / elapsed).toFixed(1)
    // console.log(`[WS] ✅ Batch ${batchId} uploaded in ${elapsed}s (${throughput} files/sec, ${mbps} Mbps)`)
  }

  _arrayBufferToBase64(buffer) {
    let binary = ''
    const bytes = new Uint8Array(buffer)
    const len = bytes.byteLength
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return window.btoa(binary)
  }

  // async _uploadFilesParallel(files, batchId) {
  //   let uploadIndex = 0
  //   const totalFiles = files.length

  //   const uploadWorker = async (workerId) => {
  //     while (uploadIndex < totalFiles) {
  //       const currentIndex = uploadIndex++
  //       const file = files[currentIndex]

  //       try {
  //         await this._uploadSingleFile(file, currentIndex, batchId)
  //       } catch (error) {
  //         console.error(`[WS] ❌ Worker ${workerId} failed on file ${currentIndex}:`, error)
  //       }
  //     }
  //   }

  //   const workers = []
  //   const workerCount = Math.min(this.maxConcurrentUploads, totalFiles)

  //   for (let i = 0; i < workerCount; i++) {
  //     workers.push(uploadWorker(i))
  //   }

  //   await Promise.all(workers)
  // }

  // async _uploadSingleFile(file, taskId, batchId) {
  //   const arrayBuffer = await file.arrayBuffer()

  //   this.ws.send(JSON.stringify({
  //     type: 'image_metadata',
  //     filename: file.name,
  //     taskId: taskId,
  //     batchId: batchId,
  //     size: arrayBuffer.byteLength
  //   }))

  //   if (arrayBuffer.byteLength > this.chunkSize) {
  //     await this._sendChunked(arrayBuffer)
  //   } else {
  //     await this._waitForBuffer()
  //     this.ws.send(arrayBuffer)
  //   }
  // }

  // async _sendChunked(arrayBuffer) {
  //   const totalChunks = Math.ceil(arrayBuffer.byteLength / this.chunkSize)

  //   for (let i = 0; i < totalChunks; i++) {
  //     const start = i * this.chunkSize
  //     const end = Math.min(start + this.chunkSize, arrayBuffer.byteLength)
  //     const chunk = arrayBuffer.slice(start, end)

  //     await this._waitForBuffer()
  //     this.ws.send(chunk)
  //   }
  // }

  // async _waitForBuffer() {
  //   if (this.ws.bufferedAmount > this.maxBufferSize) {
  //     await new Promise(resolve => {
  //       const checkBuffer = () => {
  //         if (this.ws.bufferedAmount < this.maxBufferSize / 2) {
  //           resolve()
  //         } else {
  //           setTimeout(checkBuffer, 10)
  //         }
  //       }
  //       checkBuffer()
  //     })
  //   }
  // }

  // async _waitForBufferDrain() {
  //   while (this.ws.bufferedAmount > 0) {
  //     await new Promise(resolve => setTimeout(resolve, 50))
  //     if (this.ws.bufferedAmount > 0) {
  //       console.log(`[WS] Buffer draining: ${this.ws.bufferedAmount} bytes remaining...`)
  //     }
  //   }
  //   console.log(`[WS] ✅ Buffer fully drained`)
  // }

  // getFileForResult(result) {
  //   const batchId = result.batchId
  //   const taskId = result.taskId
  //   const batchFiles = this.batchFiles.get(batchId)

  //   if (!batchFiles) {
  //     console.warn(`[WS] No batch files found for batch ${batchId}`)
  //     return null
  //   }

  //   if (taskId < 0 || taskId >= batchFiles.length) {
  //     console.warn(`[WS] Task ID ${taskId} out of range for batch ${batchId} (size: ${batchFiles.length})`)
  //     return null
  //   }

  //   const file = batchFiles[taskId]
  //   if (!file) {
  //     console.warn(`[WS] File not found for batch ${batchId}, task ${taskId}`)
  //     return null
  //   }

  //   return file
  // }

  close() {
    if (this.ws) {
      this.ws.send(JSON.stringify({ type: 'close' }))
      this.ws.close()
      this.ws = null
    }
    this.isConnected = false
    if (this.batchFiles) {
      this.batchFiles.clear()
    }
    if (this.fileMap) {
      this.fileMap.clear()
    }
  }

  getFileForResult(result) {
    const batchId = result.batchId
    const taskId = result.taskId

    // First try the direct mapping
    const key = `${batchId}_${taskId}`
    let file = this.fileMap.get(key)

    if (file) {
      console.log(`[WS] ✅ Found file via direct map: batchId=${batchId}, taskId=${taskId} -> ${file.name}`)
      return file
    }

    // Fallback to batchFiles lookup
    console.log(`[WS] Direct map miss, trying batchFiles: batchId=${batchId}, taskId=${taskId}`)
    const batchFiles = this.batchFiles.get(batchId)

    if (!batchFiles) {
      console.warn(`[WS] No batch files found for batch ${batchId}. Available batches:`, Array.from(this.batchFiles.keys()))
      console.warn(`[WS] Available fileMap keys:`, Array.from(this.fileMap.keys()))
      return null
    }

    if (taskId < 0 || taskId >= batchFiles.length) {
      console.warn(`[WS] Task ID ${taskId} out of range for batch ${batchId} (size: ${batchFiles.length})`)
      console.warn(`[WS] Batch ${batchId} files:`, batchFiles.map((f, i) => `${i}: ${f.name}`))
      return null
    }

    file = batchFiles[taskId]
    if (!file) {
      console.warn(`[WS] File not found for batch ${batchId}, task ${taskId}`)
      return null
    }

    console.log(`[WS] ✅ Matched result batchId=${batchId}, taskId=${taskId} to file: ${file.name}`)
    return file
  }
}