"""
WebSocket routes for pipelined image processing with streaming results.
Implements: Upload batch → Process batch (while uploading next) → Stream results
"""
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Optional
import asyncio
import json
import base64
from PIL import Image
import io
from workers import get_batch_queue, process_batch_async
from image_processor import process_image_sync
import time

# Store WebSocket connections and their state
_websocket_connections: Dict[str, Dict] = {}

async def websocket_process_images(websocket: WebSocket):
    """
    WebSocket endpoint for pipelined batch processing.
    
    Protocol:
    1. Client sends config: {type: 'config', backgroundColor, fileType, watermark, batchSize: 100}
    2. Client sends images: {type: 'image_metadata', filename, taskId} + binary data
    3. Client sends: {type: 'batch_end', batchId}
    4. Server processes and streams results: {type: 'image_processed', taskId, imageId, downloadUrl, ...}
    5. Server sends: {type: 'batch_complete', batchId}
    """
    await websocket.accept()
    connection_id = id(websocket)
    
    try:
        # Initialize connection state
        config = {
            'backgroundColor': 'white',
            'fileType': 'JPEG',
            'watermark': 'none',
            'batchSize': 100
        }
        
        current_batch_id = 0
        current_batch_images = []
        current_batch_filenames = []
        current_batch_data = {}  # {taskId: image_data}
        batch_queue = get_batch_queue()
        
        # Process first message (config)
        first_message = await websocket.receive()
        if first_message.get("type") == "websocket.receive":
            if "text" in first_message:
                data = json.loads(first_message["text"])
                if data.get("type") == "config":
                    config.update({
                        'backgroundColor': data.get('backgroundColor', 'white'),
                        'fileType': data.get('fileType', 'JPEG'),
                        'watermark': data.get('watermark', 'none'),
                        'batchSize': data.get('batchSize', 100)
                    })
                    await websocket.send_json({"type": "config_ack", "message": "Configuration received"})
        
        print(f"[WS] WebSocket connected, batch size: {config['batchSize']}")
        
        # Track batch completion
        batch_completion_trackers = {}  # {batch_id: {total, completed}}
        
        # Callback to send results as they complete
        async def send_result_callback(result_dict):
            """Send processed image result to client and store image"""
            try:
                batch_id = result_dict.get("batchId")
                
                # Store image data if provided (import here to avoid circular dependency)
                if "_image_data" in result_dict and "_image_id" in result_dict:
                    import main
                    main.processed_images[result_dict["_image_id"]] = {
                        "data": result_dict["_image_data"],
                        "filename": result_dict["filename"],
                        "format": result_dict["format"],
                        "mime_type": result_dict["mimeType"]
                    }
                    # Remove internal fields before sending
                    result_dict = {k: v for k, v in result_dict.items() if not k.startswith("_")}
                
                # Track batch completion
                if batch_id not in batch_completion_trackers:
                    batch_completion_trackers[batch_id] = {"completed": 0}
                batch_completion_trackers[batch_id]["completed"] += 1
                
                # Send to client immediately (streaming)
                await websocket.send_json({
                    "type": "image_processed",
                    **result_dict
                })
            except Exception as e:
                print(f"[WS] Error sending result: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # Process messages
        while True:
            message = await websocket.receive()
            
            if message.get("type") == "websocket.receive":
                # Handle text messages (metadata, commands)
                if "text" in message:
                    data = json.loads(message["text"])
                    
                    if data.get("type") == "image_metadata":
                        # Image metadata received, binary data will follow
                        task_id = data.get("taskId")
                        filename = data.get("filename", f"image_{task_id}")
                        # Store with batch-relative index
                        if task_id not in current_batch_data:
                            current_batch_data[task_id] = {
                                "filename": filename,
                                "taskId": task_id,
                                "data": None  # Will be set when binary received
                            }
                    
                    elif data.get("type") == "batch_end":
                        # All images for this batch uploaded
                        batch_id = data.get("batchId", current_batch_id)
                        expected_count = data.get("batchSize", len(current_batch_data))
                        
                        # Wait a moment for any remaining binary data to arrive
                        await asyncio.sleep(0.1)
                        
                        print(f"[WS] Batch {batch_id} upload complete, {len(current_batch_data)} images received (expected {expected_count})")
                        
                        # Prepare batch data - ensure all data is present
                        image_data_list = []
                        filenames_list = []
                        missing_data = []
                        for task_id in sorted(current_batch_data.keys()):
                            img_data = current_batch_data[task_id]
                            if img_data.get("data"):
                                image_data_list.append(img_data["data"])
                                filenames_list.append(img_data["filename"])
                            else:
                                missing_data.append(task_id)
                        
                        if missing_data:
                            print(f"[WS] Warning: Batch {batch_id} missing binary data for taskIds: {missing_data}")
                        
                        if image_data_list:
                            # Initialize batch tracker
                            batch_completion_trackers[batch_id] = {
                                "total": len(image_data_list),
                                "completed": 0
                            }
                            
                            # Notify client FIRST that batch processing will start (enables pipeline - next batch can upload)
                            # This must be sent IMMEDIATELY so frontend knows it can upload next batch
                            await websocket.send_json({
                                "type": "batch_queued",
                                "batchId": batch_id,
                                "message": f"Batch {batch_id} processing started"
                            })
                            print(f"[WS] Sent batch_queued for batch {batch_id} - frontend can now upload next batch")
                            
                            # Process batch immediately (non-blocking) - enables pipeline
                            # This allows next batch to upload while this one processes
                            async def process_and_notify_complete():
                                try:
                                    # Start processing immediately
                                    print(f"[WS] Batch {batch_id} processing started immediately (pipelined)...")
                                    
                                    await process_batch_async(
                                        batch_id,
                                        image_data_list,
                                        config['backgroundColor'],
                                        config['fileType'],
                                        config['watermark'],
                                        filenames_list,
                                        send_result_callback,
                                        None  # gpu_id (round-robin)
                                    )
                                    # Notify batch complete
                                    await websocket.send_json({
                                        "type": "batch_complete",
                                        "batchId": batch_id,
                                        "message": f"Batch {batch_id} processing completed"
                                    })
                                    print(f"[WS] Batch {batch_id} processing completed")
                                except Exception as e:
                                    print(f"[WS] Error processing batch {batch_id}: {str(e)}")
                                    import traceback
                                    traceback.print_exc()
                                    await websocket.send_json({
                                        "type": "batch_error",
                                        "batchId": batch_id,
                                        "error": str(e)
                                    })
                            
                            # Start processing immediately (non-blocking)
                            asyncio.create_task(process_and_notify_complete())
                            
                            # Reset for next batch
                            current_batch_id += 1
                            current_batch_images = []
                            current_batch_filenames = []
                            current_batch_data = {}
                        else:
                            print(f"[WS] Warning: Batch {batch_id} has no image data")
                    
                    elif data.get("type") == "close":
                        break
                
                # Handle binary messages (image data)
                elif "bytes" in message:
                    # Find the most recent task_id that doesn't have data yet
                    found = False
                    for task_id in sorted(current_batch_data.keys(), reverse=True):
                        if current_batch_data[task_id].get("data") is None:
                            current_batch_data[task_id]["data"] = message["bytes"]
                            current_batch_images.append(message["bytes"])
                            found = True
                            break
                    if not found:
                        print(f"[WS] Warning: Received binary data but no matching task_id found")
            
            elif message.get("type") == "websocket.disconnect":
                break
                
    except WebSocketDisconnect:
        print(f"[WS] WebSocket disconnected")
    except Exception as e:
        print(f"[WS] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        if connection_id in _websocket_connections:
            del _websocket_connections[connection_id]
