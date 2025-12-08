# Image Remove Background - Complete Workflow Documentation

## Overview
This project processes images in batches using a pipelined WebSocket workflow. Images are uploaded in batches of 100, and while one batch is being processed on GPU, the next batch is being uploaded simultaneously.

## Architecture

### Components
1. **Frontend** (`frontend/src/`): React app that uploads images via WebSocket
2. **Backend** (`backend/`): FastAPI server with WebSocket endpoint
3. **GPU Processing**: Uses `withoutbg` library with CUDA for background removal

### Key Files
- `frontend/src/hooks/useImageProcessing.js` - Main processing logic
- `frontend/src/services/websocketService.js` - WebSocket communication
- `backend/websocket_routes.py` - WebSocket endpoint handler
- `backend/workers.py` - Batch processing worker
- `backend/image_processor.py` - GPU image processing

---

## Complete Workflow

### Phase 1: Initialization

#### 1.1 Frontend: User Selects Images
**File**: `frontend/src/hooks/useImageProcessing.js`

```javascript
// User selects images, calls processMultipleImages()
const batches = []
for (let i = 0; i < remainingImages.length; i += BATCH_SIZE) {
  batches.push(remainingImages.slice(i, i + BATCH_SIZE))
}
// BATCH_SIZE = 100
```

#### 1.2 Frontend: Connect WebSocket
**File**: `frontend/src/services/websocketService.js` (lines 19-60)

```javascript
connect(backgroundColor, fileType, watermark, batchSize = 100) {
  // Construct WebSocket URL: wss://host/ws/process-images
  this.ws = new WebSocket(wsUrl)
  
  // Send configuration immediately on connect
  this.ws.send(JSON.stringify({
    type: 'config',
    backgroundColor: backgroundColor || 'white',
    fileType: fileType || 'JPEG',
    watermark: watermark || 'none',
    batchSize: batchSize || 100
  }))
}
```

#### 1.3 Backend: Accept Connection & Receive Config
**File**: `backend/websocket_routes.py` (lines 30-60)

```python
await websocket.accept()

# Receive first message (config)
first_message = await websocket.receive()
data = json.loads(first_message["text"])
if data.get("type") == "config":
    config.update({
        'backgroundColor': data.get('backgroundColor', 'white'),
        'fileType': data.get('fileType', 'JPEG'),
        'watermark': data.get('watermark', 'none'),
        'batchSize': data.get('batchSize', 100)
    })
    await websocket.send_json({"type": "config_ack"})
```

---

### Phase 2: Batch Upload & Processing (Pipelined)

#### 2.1 Frontend: Upload Batch 0
**File**: `frontend/src/hooks/useImageProcessing.js` (lines 230-246)

```javascript
if (batchIndex === 0) {
  // First batch: upload immediately
  console.log(`[WS] Uploading batch 0 (100 images)`)
  await ws.sendBatch(batch, 0)
  
  // Wait for batch_queued (GPU started processing)
  while (!ws.batchQueued.has(0) && waitCount < 200) {
    await new Promise(resolve => setTimeout(resolve, 50))
    waitCount++
  }
}
```

#### 2.2 Frontend: Send Batch Images
**File**: `frontend/src/services/websocketService.js` (lines 150-197)

```javascript
sendBatch(files, batchId) {
  const sendNext = (index) => {
    if (index >= files.length) {
      // All files sent, send batch_end
      this.ws.send(JSON.stringify({
        type: 'batch_end',
        batchId: batchId,
        batchSize: totalFiles
      }))
      return
    }
    
    const file = files[index]
    const taskId = index  // 0-99 within batch
    
    // Send metadata
    this.ws.send(JSON.stringify({
      type: 'image_metadata',
      filename: file.name,
      taskId: taskId
    }))
    
    // Send binary data
    reader.readAsArrayBuffer(file)
    this.ws.send(reader.result)  // Binary data
    
    sendNext(index + 1)
  }
  sendNext(0)
}
```

**Message Flow for Each Image:**
1. `{type: 'image_metadata', filename: 'img.jpg', taskId: 0}` (JSON)
2. `<binary image data>` (ArrayBuffer)

#### 2.3 Backend: Receive Images
**File**: `backend/websocket_routes.py` (lines 100-120, 192-198)

```python
while True:
    message = await websocket.receive()
    
    if "text" in message:
        data = json.loads(message["text"])
        
        if data.get("type") == "image_metadata":
            task_id = data.get("taskId")
            filename = data.get("filename")
            current_batch_data[task_id] = {
                "filename": filename,
                "taskId": task_id,
                "data": None  # Will be set when binary received
            }
    
    elif "bytes" in message:
        # Find task_id that doesn't have data yet
        for task_id in sorted(current_batch_data.keys(), reverse=True):
            if current_batch_data[task_id]["data"] is None:
                current_batch_data[task_id]["data"] = message["bytes"]
                break
```

#### 2.4 Backend: Receive batch_end & Start Processing
**File**: `backend/websocket_routes.py` (lines 121-197)

```python
elif data.get("type") == "batch_end":
    batch_id = data.get("batchId", 0)
    expected_count = data.get("batchSize", 100)
    
    # Wait for any remaining binary data
    await asyncio.sleep(0.1)
    
    # Prepare batch data
    image_data_list = []
    filenames_list = []
    for task_id in sorted(current_batch_data.keys()):
        img_data = current_batch_data[task_id]
        if img_data.get("data"):
            image_data_list.append(img_data["data"])
            filenames_list.append(img_data["filename"])
    
    # Send batch_queued IMMEDIATELY (enables pipeline)
    await websocket.send_json({
        "type": "batch_queued",
        "batchId": batch_id,
        "message": f"Batch {batch_id} processing started"
    })
    
    # Start processing (non-blocking)
    async def process_and_notify_complete():
        await process_batch_async(
            batch_id,
            image_data_list,
            config['backgroundColor'],
            config['fileType'],
            config['watermark'],
            filenames_list,
            send_result_callback,  # Called for each image
            None  # gpu_id (round-robin)
        )
        # Send batch_complete when done
        await websocket.send_json({
            "type": "batch_complete",
            "batchId": batch_id
        })
    
    asyncio.create_task(process_and_notify_complete())
```

**Key Point**: `batch_queued` is sent BEFORE processing starts, allowing frontend to upload next batch immediately.

#### 2.5 Frontend: Receive batch_queued & Upload Batch 1
**File**: `frontend/src/hooks/useImageProcessing.js` (lines 247-282)

```javascript
else {
  // For batch 1, 2, 3...
  const prevBatchId = batchIndex - 1
  
  // Wait for previous batch to be queued (processing started)
  while (!ws.batchQueued.has(prevBatchId) && waitCount < 200) {
    await new Promise(resolve => setTimeout(resolve, 50))
    waitCount++
  }
  
  // Previous batch is now processing, upload this batch
  console.log(`[WS] Batch ${prevBatchId} is processing, uploading batch ${batchId}`)
  await ws.sendBatch(batch, batchId)
  
  // Wait for this batch to be queued
  while (!ws.batchQueued.has(batchId) && waitCount < 200) {
    await new Promise(resolve => setTimeout(resolve, 50))
    waitCount++
  }
}
```

**Pipelining**: While Batch 0 is processing on GPU, Batch 1 is uploading simultaneously.

---

### Phase 3: GPU Processing & Streaming Results

#### 3.1 Backend: Process Images Concurrently
**File**: `backend/workers.py` (lines 22-146)

```python
async def process_batch_async(batch_id, image_data_list, ...):
    # Process images individually for streaming
    async def process_single_with_callback(idx, image_data, filename):
        # Get GPU ID (round-robin)
        actual_gpu_id = _batch_gpu_counter % NUM_GPUS
        
        # Process in thread pool (GPU operation)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            process_image_sync,  # GPU processing function
            image_data,
            bg_color,
            output_format,
            watermark_option,
            filename,
            actual_gpu_id
        )
        
        # Create result dict
        result_dict = {
            "batchId": batch_id,
            "taskId": idx,
            "success": True,
            "imageId": f"img_{batch_id}_{idx}_{timestamp}",
            "downloadUrl": f"/api/download?imageId={image_id}",
            "_image_data": processed_bytes,  # For storage
            "_image_id": image_id
        }
        
        # Call callback IMMEDIATELY (streaming)
        if callback:
            await callback(result_dict)
    
    # Process all images concurrently (with semaphore limit)
    max_concurrent = min(10, NUM_GPUS * 2)
    semaphore = asyncio.Semaphore(max_concurrent)
    
    tasks = [
        process_with_semaphore(idx, image_data, filenames[idx])
        for idx, image_data in enumerate(image_data_list)
    ]
    
    await asyncio.gather(*tasks)  # Process all concurrently
```

#### 3.2 Backend: Send Results as They Complete
**File**: `backend/websocket_routes.py` (lines 68-98)

```python
async def send_result_callback(result_dict):
    # Store image data
    if "_image_data" in result_dict:
        import main
        main.processed_images[result_dict["_image_id"]] = {
            "data": result_dict["_image_data"],
            "filename": result_dict["filename"],
            "format": result_dict["format"],
            "mime_type": result_dict["mimeType"]
        }
        # Remove internal fields
        result_dict = {k: v for k, v in result_dict.items() if not k.startswith("_")}
    
    # Send to client IMMEDIATELY (streaming)
    await websocket.send_json({
        "type": "image_processed",
        **result_dict
    })
```

#### 3.3 Frontend: Receive & Display Results
**File**: `frontend/src/hooks/useImageProcessing.js` (lines 157-199)

```javascript
// onResult callback
async (result) => {
  if (result.type === 'image_processed' && result.success) {
    // Download image from backend
    const response = await fetch(result.downloadUrl)
    const imageBlob = await response.blob()
    const processedUrl = URL.createObjectURL(imageBlob)
    
    // Find corresponding file
    const file = ws.getFileForResult(result)
    
    // Add to processed images (displays immediately)
    const processedImage = {
      file,
      originalUrl: originalUrlsMap.get(file),
      processedUrl: processedUrl,
      imageId: result.imageId
    }
    
    setProcessedImages(prev => [...prev, processedImage])
  }
}
```

**File**: `frontend/src/services/websocketService.js` (lines 62-99)

```javascript
this.ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  
  if (data.type === 'image_processed') {
    // Individual image processed - send to frontend immediately
    if (this.onResult) {
      this.onResult(data)
    }
  } else if (data.type === 'batch_complete') {
    this.batchComplete.add(data.batchId)
    if (this.onResult) {
      this.onResult(data)
    }
  } else if (data.type === 'batch_queued') {
    this.batchQueued.add(data.batchId)
    if (this.onResult) {
      this.onResult(data)
    }
  }
}
```

---

## Complete Message Flow Example

### Batch 0 (100 images)

```
1. Frontend → Backend: {type: 'config', backgroundColor: 'white', ...}
2. Backend → Frontend: {type: 'config_ack'}

3. Frontend → Backend: {type: 'image_metadata', filename: 'img0.jpg', taskId: 0}
4. Frontend → Backend: <binary data for img0.jpg>
5. Frontend → Backend: {type: 'image_metadata', filename: 'img1.jpg', taskId: 1}
6. Frontend → Backend: <binary data for img1.jpg>
... (repeat for all 100 images)
7. Frontend → Backend: {type: 'batch_end', batchId: 0, batchSize: 100}

8. Backend → Frontend: {type: 'batch_queued', batchId: 0}  ← Frontend can now upload batch 1

9. Backend starts processing batch 0 on GPU (non-blocking)

10. Backend → Frontend: {type: 'image_processed', batchId: 0, taskId: 0, imageId: '...', ...}  ← Image 0 done
11. Backend → Frontend: {type: 'image_processed', batchId: 0, taskId: 1, imageId: '...', ...}  ← Image 1 done
... (streaming results as each image completes)

12. Backend → Frontend: {type: 'batch_complete', batchId: 0}  ← All 100 images done
```

### Batch 1 (99 images) - Uploads while Batch 0 is processing

```
13. Frontend → Backend: {type: 'image_metadata', filename: 'img100.jpg', taskId: 0}  ← Batch 1 starts
14. Frontend → Backend: <binary data for img100.jpg>
... (upload continues while batch 0 processes)
15. Frontend → Backend: {type: 'batch_end', batchId: 1, batchSize: 99}

16. Backend → Frontend: {type: 'batch_queued', batchId: 1}  ← Frontend can upload batch 2

17. Backend starts processing batch 1 on GPU (batch 0 may still be processing)
18. Backend → Frontend: {type: 'image_processed', batchId: 1, taskId: 0, ...}  ← Batch 1 results stream
...
```

---

## Key Design Decisions

### 1. Pipelining
- **Why**: Maximize GPU utilization. While one batch processes, next batch uploads.
- **How**: `batch_queued` message signals frontend that processing started, enabling next upload.

### 2. Streaming Results
- **Why**: User sees progress in real-time, not waiting for entire batch.
- **How**: Each image calls `send_result_callback` immediately when done.

### 3. Concurrent Processing
- **Why**: Process multiple images simultaneously on GPU for speed.
- **How**: `asyncio.gather()` with semaphore limiting (max 10 concurrent per batch).

### 4. Round-Robin GPU Assignment
- **Why**: Distribute load across multiple GPUs.
- **How**: `actual_gpu_id = _batch_gpu_counter % NUM_GPUS`

### 5. WebSocket Instead of HTTP
- **Why**: 
  - Bidirectional communication (upload + streaming results)
  - Long-lived connection for multiple batches
  - Real-time progress updates

---

## File Structure

```
backend/
├── main.py                 # FastAPI app, WebSocket endpoint registration
├── websocket_routes.py     # WebSocket message handling, batch coordination
├── workers.py              # Batch processing, concurrent GPU operations
├── image_processor.py      # GPU image processing (withoutbg library)
└── gpu_manager.py          # GPU initialization, instance management

frontend/src/
├── hooks/
│   └── useImageProcessing.js  # Main processing logic, batch coordination
└── services/
    └── websocketService.js    # WebSocket communication, message handling
```

---

## Error Handling

1. **Missing Binary Data**: Backend waits 0.1s after `batch_end` for any remaining binary
2. **WebSocket Disconnect**: Backend catches `WebSocketDisconnect` and cleans up
3. **Processing Errors**: Each image error is sent as `{type: 'image_processed', success: false, error: '...'}`
4. **Batch Errors**: Sent as `{type: 'batch_error', batchId: X, error: '...'}`

---

## Performance Characteristics

- **Batch Size**: 100 images per batch (fixed)
- **Concurrent Processing**: Up to 10 images simultaneously (or `NUM_GPUS * 2`)
- **GPU Assignment**: Round-robin across available GPUs
- **Result Streaming**: Each image sent immediately when done (no batching of results)

---

This workflow ensures:
1. ✅ GPU is always busy (pipelining)
2. ✅ User sees progress in real-time (streaming)
3. ✅ Efficient resource utilization (concurrent processing)
4. ✅ Scalable across multiple GPUs (round-robin)
