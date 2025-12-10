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
from workers import get_batch_queue, process_batch_async, get_processing_semaphore
from image_processor import process_image_sync
import uuid
import time
import zipfile
import os
import tempfile

# Store WebSocket connections and their state
_websocket_connections: Dict[str, Dict] = {}

processed_images_store = None

def set_processed_images_store(store):
    global processed_images_store
    processed_images_store = store


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
    
    # Track active processing tasks
    active_tasks = []
    
    # Use a dict to track connection state (mutable, accessible in nested functions)
    connection_state = {
        'closed': False
    }
    
    try:
        # Initialize connection state
        config = {
            'backgroundColor': 'white',
            'fileType': 'JPEG',
            'watermark': 'none',
            'batchSize': 100,
            'returnBase64': True  # allow skipping base64 to reduce payload
        }
        
        current_batch_id = 0
        batch_counters = {}  # batch_id -> {"total": int, "done": int}
        batch_state = {}     # batch_id -> {"queued_sent": bool, "processing": bool}
        
        # Batch collection: {batch_id: {"images": [...], "filenames": [...], "complete": bool}}
        batch_data = {}
        
        # Zip file management (using dict to avoid closure issues)
        zip_state = {
            "file": None,
            "path": None,
            "images_added": 0  # Track how many images have been added to zip
        }
        zip_lock = asyncio.Lock()
        total_images_expected = 0
        total_images_processed = 0
        all_batches_complete = False
        
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
                        'batchSize': data.get('batchSize', 100),
                        'returnBase64': data.get('returnBase64', True)
                    })
                    await websocket.send_json({"type": "config_ack", "message": "Configuration received"})
        
        print(f"[WS] WebSocket connected, batch size: {config['batchSize']}")
        
        # Per-image pending metadata (for current batch being uploaded)
        pending_images = []
        semaphore = get_processing_semaphore()
        
        async def create_zip_file():
            """Create a new zip file when processing starts"""
            nonlocal total_images_expected, total_images_processed
            async with zip_lock:
                if zip_state["file"] is None:
                    # Create zip file in temp directory
                    temp_dir = tempfile.gettempdir()
                    zip_state["path"] = os.path.join(temp_dir, f"processed_images_{uuid.uuid4().hex[:12]}.zip")
                    zip_state["file"] = zipfile.ZipFile(zip_state["path"], 'w', zipfile.ZIP_DEFLATED)
                    print(f"[WS] Created zip file: {zip_state['path']}")
                    
                    # Add any images that were already processed via /api/upload
                    if processed_images_store is not None:
                        print(f"[WS] Checking processed_images_store for pre-uploaded images (store has {len(processed_images_store)} entries)")
                        pre_uploaded_count = 0
                        for image_id, image_data in processed_images_store.items():
                            print(f"[WS] Checking entry: {image_id}, type: {type(image_data)}, is_dict: {isinstance(image_data, dict)}")
                            # Skip zip entries and entries without data
                            if image_id.startswith("zip_"):
                                print(f"[WS] Skipping zip entry: {image_id}")
                                continue
                            if not isinstance(image_data, dict):
                                print(f"[WS] Skipping non-dict entry: {image_id} (type: {type(image_data)})")
                                continue
                            if "data" not in image_data or image_data["data"] is None:
                                print(f"[WS] Skipping entry without data: {image_id}")
                                continue
                            # Only include images marked as pre-uploaded via /api/upload
                            if not image_data.get("pre_uploaded", False):
                                print(f"[WS] Skipping entry not marked as pre-uploaded: {image_id}")
                                continue
                            
                            # Add pre-uploaded image to zip with unique filename
                            pre_filename = image_data.get("filename", f"pre_uploaded_{image_id}.jpg")
                            unique_pre_filename = f"pre_{image_id}_{pre_filename}"
                            try:
                                zip_state["file"].writestr(unique_pre_filename, image_data["data"])
                                zip_state["images_added"] += 1
                                pre_uploaded_count += 1
                                print(f"[WS] Added pre-uploaded image {image_id} ({pre_filename}) to zip as {unique_pre_filename}")
                            except Exception as e:
                                print(f"[WS] Error adding pre-uploaded image {image_id} to zip: {str(e)}")
                                import traceback
                                traceback.print_exc()
                        
                        if pre_uploaded_count > 0:
                            # Update total expected and processed to include pre-uploaded images
                            total_images_expected += pre_uploaded_count
                            total_images_processed += pre_uploaded_count
                            print(f"[WS] Added {pre_uploaded_count} pre-uploaded image(s) to zip, total_images_expected: {total_images_expected}, total_images_processed: {total_images_processed}")
                        else:
                            print(f"[WS] No pre-uploaded images found in processed_images_store")
                    else:
                        print(f"[WS] processed_images_store is None, cannot add pre-uploaded images")
        
        async def add_to_zip(image_id: str, image_bytes: bytes, filename: str):
            """Add processed image to zip file incrementally"""
            nonlocal total_images_expected, total_images_processed
            try:
                async with zip_lock:
                    # Ensure zip file exists (should be created before processing starts)
                    if zip_state["file"] is None:
                        # Create zip file if it doesn't exist (shouldn't happen, but safety check)
                        temp_dir = tempfile.gettempdir()
                        zip_state["path"] = os.path.join(temp_dir, f"processed_images_{uuid.uuid4().hex[:12]}.zip")
                        zip_state["file"] = zipfile.ZipFile(zip_state["path"], 'w', zipfile.ZIP_DEFLATED)
                        print(f"[WS] Created zip file: {zip_state['path']}")
                        
                        # Add any images that were already processed via /api/upload
                        if processed_images_store is not None:
                            print(f"[WS] Checking processed_images_store for pre-uploaded images (store has {len(processed_images_store)} entries)")
                            pre_uploaded_count = 0
                            for pre_image_id, pre_image_data in processed_images_store.items():
                                print(f"[WS] Checking entry: {pre_image_id}, type: {type(pre_image_data)}, is_dict: {isinstance(pre_image_data, dict)}")
                                # Skip zip entries and entries without data
                                if pre_image_id.startswith("zip_"):
                                    print(f"[WS] Skipping zip entry: {pre_image_id}")
                                    continue
                                if not isinstance(pre_image_data, dict):
                                    print(f"[WS] Skipping non-dict entry: {pre_image_id} (type: {type(pre_image_data)})")
                                    continue
                                if "data" not in pre_image_data or pre_image_data["data"] is None:
                                    print(f"[WS] Skipping entry without data: {pre_image_id}")
                                    continue
                                # Only include images marked as pre-uploaded via /api/upload
                                if not pre_image_data.get("pre_uploaded", False):
                                    print(f"[WS] Skipping entry not marked as pre-uploaded: {pre_image_id}")
                                    continue
                                
                                # Add pre-uploaded image to zip with unique filename
                                pre_filename = pre_image_data.get("filename", f"pre_uploaded_{pre_image_id}.jpg")
                                unique_pre_filename = f"pre_{pre_image_id}_{pre_filename}"
                                try:
                                    zip_state["file"].writestr(unique_pre_filename, pre_image_data["data"])
                                    zip_state["images_added"] += 1
                                    pre_uploaded_count += 1
                                    print(f"[WS] Added pre-uploaded image {pre_image_id} ({pre_filename}) to zip as {unique_pre_filename}")
                                except Exception as e:
                                    print(f"[WS] Error adding pre-uploaded image {pre_image_id} to zip: {str(e)}")
                                    import traceback
                                    traceback.print_exc()
                            
                            if pre_uploaded_count > 0:
                                # Update total expected and processed to include pre-uploaded images
                                total_images_expected += pre_uploaded_count
                                total_images_processed += pre_uploaded_count
                                print(f"[WS] Added {pre_uploaded_count} pre-uploaded image(s) to zip, total_images_expected: {total_images_expected}, total_images_processed: {total_images_processed}")
                            else:
                                print(f"[WS] No pre-uploaded images found in processed_images_store")
                        else:
                            print(f"[WS] processed_images_store is None, cannot add pre-uploaded images")
                    
                    print(f"[WS] Adding {filename} (image_id: {image_id}, size: {len(image_bytes)} bytes) to zip...")
                    # Add image to zip
                    zip_state["file"].writestr(filename, image_bytes)
                    zip_state["images_added"] += 1
                    print(f"[WS] Successfully added {filename} to zip file (total: {zip_state['images_added']}/{total_images_expected})")
            except Exception as e:
                print(f"[WS] ERROR adding {filename} (image_id: {image_id}) to zip: {str(e)}")
                import traceback
                traceback.print_exc()
                # Re-raise to ensure we know about the failure
                raise
        
        async def finalize_zip():
            """Close zip file and return download URL"""
            async with zip_lock:
                if zip_state["file"] is not None:
                    zip_state["file"].close()
                    print(f"[WS] Finalized zip file: {zip_state['path']}")
                    # Move zip to a permanent location accessible via download endpoint
                    # For now, return the temp path - you may want to move it to a static directory
                    return zip_state["path"]
            return None
        
        async def process_and_send(batch_id, task_id, filename, image_bytes):
            if connection_state['closed']:
                return
            try:
                async with semaphore:
                    loop = asyncio.get_event_loop()
                    output_bytes, mime_type, output_filename, save_format = await loop.run_in_executor(
                        None,
                        process_image_sync,
                        image_bytes,
                        config['backgroundColor'],
                        config['fileType'],
                        config['watermark'],
                        filename,
                        None  # gpu_id (round-robin inside)
                    )
                
                # Build response
                image_url = None
                if config.get('returnBase64', True):
                    image_base64 = base64.b64encode(output_bytes).decode('utf-8')
                    image_url = f"data:{mime_type};base64,{image_base64}"
                image_id = f"img_{uuid.uuid4().hex[:12]}"
                download_url = f"/api/download?imageId={image_id}"
                
                # Store processed image for download if store is available
                if processed_images_store is not None:
                    processed_images_store[image_id] = {
                        "data": output_bytes,
                        "filename": output_filename,
                        "format": save_format,
                        "mime_type": mime_type
                    }
                
                # Add to zip file immediately
                await add_to_zip(image_id, output_bytes, output_filename)
                
                if connection_state['closed']:
                    return
                
                # Send result immediately to frontend
                await websocket.send_json({
                    "type": "image_processed",
                    "batchId": batch_id,
                    "taskId": task_id,
                    "filename": output_filename,
                    "downloadUrl": download_url,
                    "imageId": image_id,
                    "format": save_format,
                    "mimeType": mime_type,
                    "success": True,
                    **({"imageUrl": image_url} if image_url else {})
                })
                print(f"[WS] Result sent successfully for batch {batch_id}, task {task_id}")
                
                # This function is no longer used - batch processing uses send_result_callback
                # Keeping for reference but it won't be called
                pass
            except WebSocketDisconnect:
                print(f"[WS] WebSocket disconnected while processing task {task_id}")
                connection_state['closed'] = True
            except Exception as e:
                print(f"[WS] Error processing task {task_id}: {str(e)}")
                import traceback
                traceback.print_exc()
                if not connection_state['closed']:
                    try:
                        await websocket.send_json({
                            "type": "image_error",
                            "taskId": task_id,
                            "error": str(e)
                        })
                    except:
                        pass
        
        # Process messages (per-image streaming, no batches)
        while not connection_state['closed']:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                print(f"[WS] WebSocket disconnected while receiving message")
                connection_state['closed'] = True
                break
            
            if message.get("type") == "websocket.receive":
                # Handle text messages (metadata, commands)
                if "text" in message:
                    data = json.loads(message["text"])
                    
                    if data.get("type") == "batch_upload":
                        # New protocol: Frontend sends all 100 images metadata at once
                        batch_id = data.get("batchId", current_batch_id)
                        images_metadata = data.get("images", [])  # [{taskId, filename}, ...]
                        
                        print(f"[WS] Received batch_upload for batch {batch_id} with {len(images_metadata)} images")
                        
                        # Initialize batch state
                        if batch_id not in batch_counters:
                            batch_counters[batch_id] = {"total": len(images_metadata), "done": 0}
                        if batch_id not in batch_state:
                            batch_state[batch_id] = {"queued_sent": False, "processing": False, "expecting_binary": True}
                        
                        # Create pending images list for this batch
                        for img_meta in images_metadata:
                            pending_images.append({
                                "taskId": img_meta.get("taskId"),
                                "filename": img_meta.get("filename", f"image_{img_meta.get('taskId')}"),
                                "batchId": batch_id,
                                "data": None
                            })
                        
                        # Update counters
                        if batch_id not in batch_counters:
                            batch_counters[batch_id] = {"total": len(images_metadata), "done": 0}
                        else:
                            batch_counters[batch_id]["total"] = len(images_metadata)
                        
                        # Update total expected
                        total_images_expected += len(images_metadata)
                        print(f"[WS] Updated total_images_expected to {total_images_expected} (added {len(images_metadata)} from batch {batch_id})")
                        
                        # Create zip file as early as possible (when first batch metadata is received)
                        if zip_state["file"] is None:
                            await create_zip_file()
                        
                        # Send acknowledgment
                        await websocket.send_json({
                            "type": "batch_upload_ack",
                            "batchId": batch_id,
                            "message": f"Batch {batch_id} metadata received, ready for binary data",
                            "expectedCount": len(images_metadata)
                        })
                        print(f"[WS] Sent batch_upload_ack for batch {batch_id}, expecting {len(images_metadata)} binary messages")
                    
                    elif data.get("type") == "image_metadata":
                        task_id = data.get("taskId")
                        filename = data.get("filename", f"image_{task_id}")
                        batch_id = data.get("batchId", current_batch_id)
                        print(f"[WS] Received metadata for task {task_id} (batch {batch_id}): {filename}")
                        if batch_id not in batch_counters:
                            batch_counters[batch_id] = {"total": 0, "done": 0}
                        if batch_id not in batch_state:
                            batch_state[batch_id] = {"queued_sent": False, "processing": False}
                        # For clients waiting on batch_queued, emit it as soon as we see first metadata
                        if not batch_state[batch_id]["queued_sent"]:
                            try:
                                await websocket.send_json({
                                    "type": "batch_queued",
                                    "batchId": batch_id,
                                    "message": f"Batch {batch_id} processing started"
                                })
                                batch_state[batch_id]["queued_sent"] = True
                                print(f"[WS] Sent batch_queued for batch {batch_id} (on metadata)")
                            except Exception as e:
                                print(f"[WS] Error sending batch_queued: {str(e)}")
                        pending_images.append({
                            "taskId": task_id,
                                "filename": filename,
                            "batchId": batch_id,
                            "data": None
                        })
                    
                    elif data.get("type") == "batch_end":
                        batch_id = data.get("batchId", current_batch_id)
                        expected_count = data.get("batchSize", len(pending_images))
                        
                        # Collect all images for this batch - sort by taskId to ensure correct order
                        batch_images = []
                        batch_filenames = []
                        batch_task_ids = []
                        
                        # Get all images for this batch, sorted by taskId
                        batch_pending_sorted = sorted(
                            [img for img in pending_images if img.get("batchId") == batch_id and img.get("data") is not None],
                            key=lambda x: x.get("taskId", 999)
                        )
                        
                        for img in batch_pending_sorted:
                            batch_images.append(img["data"])
                            batch_filenames.append(img["filename"])
                            batch_task_ids.append(img.get("taskId"))
                        
                        print(f"[WS] Received batch_end for batch {batch_id}, collected {len(batch_images)} images, taskIds: {batch_task_ids}")
                        
                        # Store batch data
                        batch_data[batch_id] = {
                            "images": batch_images,
                            "filenames": batch_filenames,
                            "complete": True
                        }
                        
                        # Update counters
                        if batch_id not in batch_counters:
                            batch_counters[batch_id] = {"total": len(batch_images), "done": 0}
                        else:
                            batch_counters[batch_id]["total"] = len(batch_images)
                        
                        if batch_id not in batch_state:
                            batch_state[batch_id] = {"queued_sent": False, "processing": False}
                        
                        # Update total expected images (no nonlocal needed - it's in outer scope)
                        total_images_expected += len(batch_images)
                        print(f"[WS] Updated total_images_expected to {total_images_expected} (added {len(batch_images)} from batch {batch_id})")
                        
                        # Send batch_queued immediately
                        if not batch_state[batch_id]["queued_sent"]:
                            try:
                                # Create zip file when first batch starts processing
                                if zip_state["file"] is None:
                                    await create_zip_file()
                                
                                await websocket.send_json({
                                "type": "batch_queued",
                                "batchId": batch_id,
                                "message": f"Batch {batch_id} processing started"
                                })
                                batch_state[batch_id]["queued_sent"] = True
                                print(f"[WS] Sent batch_queued for batch {batch_id}")
                            except Exception as e:
                                print(f"[WS] Error sending batch_queued: {str(e)}")
                        
                        # Start processing batch immediately (non-blocking)
                        if not batch_state[batch_id]["processing"] and len(batch_images) > 0:
                            batch_state[batch_id]["processing"] = True
                            
                            async def send_result_callback(result_dict):
                                """Callback to send individual results as they complete"""
                                # Declare nonlocal variables at the top of the nested function
                                nonlocal total_images_processed, total_images_expected, all_batches_complete
                                
                                if connection_state['closed']:
                                    return
                                
                                batch_id_cb = result_dict.get("batchId")
                                task_id = result_dict.get("taskId")
                                output_bytes = result_dict.get("_image_data")
                                image_id = result_dict.get("_imageId")
                                output_filename = result_dict.get("filename")
                                mime_type = result_dict.get("mimeType")
                                save_format = result_dict.get("format")
                                
                                print(f"[WS] Callback received for batch {batch_id_cb}, task {task_id}, image_id: {image_id}, filename: {output_filename}, has_data: {output_bytes is not None}")
                                
                                if not output_bytes or not image_id:
                                    print(f"[WS] WARNING: Skipping image - output_bytes: {output_bytes is not None}, image_id: {image_id}")
                                    return
                                
                                # Build response
                                image_url = None
                                if config.get('returnBase64', True):
                                    image_base64 = base64.b64encode(output_bytes).decode('utf-8')
                                    image_url = f"data:{mime_type};base64,{image_base64}"
                                
                                download_url = f"/api/download?imageId={image_id}"
                                
                                # Store processed image
                                if processed_images_store is not None:
                                    processed_images_store[image_id] = {
                                        "data": output_bytes,
                                        "filename": output_filename,
                                        "format": save_format,
                                        "mime_type": mime_type
                                    }
                                
                                # Add to zip file immediately (use unique filename to avoid overwrites)
                                # Include task_id in filename to ensure uniqueness
                                unique_filename = f"{task_id}_{output_filename}" if task_id is not None else f"{image_id}_{output_filename}"
                                try:
                                    await add_to_zip(image_id, output_bytes, unique_filename)
                                except Exception as zip_error:
                                    print(f"[WS] CRITICAL: Failed to add image {image_id} (task {task_id}) to zip: {str(zip_error)}")
                                    # Don't continue if zip add fails - this is critical
                                    raise
                                
                                # Send result immediately
                                await websocket.send_json({
                                    "type": "image_processed",
                                    "batchId": batch_id_cb,
                                    "taskId": task_id,
                                    "filename": output_filename,
                                    "downloadUrl": download_url,
                                    "imageId": image_id,
                                    "format": save_format,
                                    "mimeType": mime_type,
                                    "success": True,
                                    **({"imageUrl": image_url} if image_url else {})
                                })
                                
                                # Track completion
                                total_images_processed += 1
                                print(f"[WS] Progress: {total_images_processed}/{total_images_expected} processed, {zip_state['images_added']}/{total_images_expected} added to zip")
                                
                                if batch_id_cb in batch_counters:
                                    batch_counters[batch_id_cb]["done"] += 1
                                    if (batch_counters[batch_id_cb]["done"] >= batch_counters[batch_id_cb]["total"] 
                                        and not connection_state['closed']):
                                        try:
                                            await websocket.send_json({
                                                "type": "batch_complete",
                                                "batchId": batch_id_cb,
                                                "message": f"Batch {batch_id_cb} processing completed"
                                            })
                                        except Exception as e:
                                            print(f"[WS] Error sending batch_complete: {str(e)}")
                                
                                # Check if all images are processed AND added to zip
                                if (total_images_processed >= total_images_expected and 
                                    total_images_expected > 0 and
                                    zip_state["images_added"] >= total_images_expected):
                                    if not all_batches_complete:
                                        all_batches_complete = True
                                        print(f"[WS] All {total_images_processed} images processed and {zip_state['images_added']} added to zip, finalizing...")
                                        zip_path = await finalize_zip()
                                        zip_id = os.path.basename(zip_path).replace('.zip', '') if zip_path else None
                                        if zip_id and processed_images_store is not None:
                                            processed_images_store[f"zip_{zip_id}"] = {
                                                "data": None,
                                                "filename": f"processed_images_{zip_id}.zip",
                                                "format": "ZIP",
                                                "mime_type": "application/zip",
                                                "file_path": zip_path
                                            }
                                        
                                        if not connection_state['closed']:
                                            try:
                                                all_complete_msg = {
                                                    "type": "all_complete",
                                                    "message": "All images processed",
                                                    "zipDownloadUrl": f"/api/download?imageId=zip_{zip_id}" if zip_id else None,
                                                    "totalProcessed": total_images_processed,
                                                    "totalImages": zip_state["images_added"]  # Total images in zip (includes pre-uploaded)
                                                }
                                                print(f"[WS] Sending all_complete: totalProcessed={total_images_processed}, totalImages={zip_state['images_added']}, zip_id={zip_id}")
                                                await websocket.send_json(all_complete_msg)
                                            except Exception as e:
                                                print(f"[WS] Error sending all_complete: {str(e)}")
                            
                            async def process_batch():
                                try:
                                    print(f"[WS] Starting batch {batch_id} processing with {len(batch_images)} images")
                                    await process_batch_async(
                                        batch_id,
                                        batch_images,
                                        config['backgroundColor'],
                                        config['fileType'],
                                        config['watermark'],
                                        batch_filenames,
                                        send_result_callback,
                                        None  # gpu_id (round-robin)
                                    )
                                    print(f"[WS] Batch {batch_id} processing completed")
                                except Exception as e:
                                    print(f"[WS] Error processing batch {batch_id}: {str(e)}")
                                    import traceback
                                    traceback.print_exc()
                                    
                            # Start batch processing task
                            batch_task = asyncio.create_task(process_batch())
                            active_tasks.append(batch_task)
                        
                        # Clear pending images for this batch and advance batch id
                        pending_images = [img for img in pending_images if img.get("batchId") != batch_id]
                        current_batch_id = batch_id + 1
                    
                    elif data.get("type") == "close":
                        print(f"[WS] Received close request from client")
                        break
                
                # Handle binary messages (image data)
                elif "bytes" in message:
                    binary_size = len(message["bytes"])
                    
                    # Match binary to the first pending image without data (FIFO order)
                    target = None
                    for img in pending_images:
                        if img["data"] is None:
                            target = img
                            break
                    
                    if not target:
                        print(f"[WS] Warning: Received binary data ({binary_size} bytes) but no pending metadata found")
                        continue
                    
                    target["data"] = message["bytes"]
                    batch_id_for_task = target.get("batchId", current_batch_id)
                    task_id_received = target.get("taskId")
                    print(f"[WS] Received binary data for task {task_id_received} (batch {batch_id_for_task}): {binary_size} bytes")
                    print(f"[WS] Pending images status: {[(img.get('taskId'), img.get('batchId'), 'has_data' if img.get('data') else 'no_data') for img in pending_images if img.get('batchId') == batch_id_for_task]}")
                    
                    # Ensure counters/state
                    if batch_id_for_task not in batch_counters:
                        batch_counters[batch_id_for_task] = {"total": 0, "done": 0}
                    if batch_id_for_task not in batch_state:
                        batch_state[batch_id_for_task] = {"queued_sent": False, "processing": False, "expecting_binary": True}
                    
                    # Check if all images for this batch have been received
                    batch_pending = [img for img in pending_images if img.get("batchId") == batch_id_for_task and img.get("data") is None]
                    batch_received = [img for img in pending_images if img.get("batchId") == batch_id_for_task and img.get("data") is not None]
                    
                    # If all images for this batch are received, automatically trigger processing
                    if batch_id_for_task in batch_counters:
                        expected_count = batch_counters[batch_id_for_task]["total"]
                        if len(batch_received) >= expected_count and expected_count > 0:
                            # All images received, trigger batch processing
                            if not batch_state[batch_id_for_task].get("processing", False):
                                print(f"[WS] All {expected_count} images received for batch {batch_id_for_task}, starting processing...")
                                
                                # Collect batch data - sort by taskId to ensure correct order
                                batch_images = []
                                batch_filenames = []
                                batch_task_ids = []  # Track taskIds to ensure we have all images
                                
                                # Get all images for this batch, sorted by taskId
                                batch_pending_sorted = sorted(
                                    [img for img in pending_images if img.get("batchId") == batch_id_for_task and img.get("data") is not None],
                                    key=lambda x: x.get("taskId", 999)
                                )
                                
                                for img in batch_pending_sorted:
                                    batch_images.append(img["data"])
                                    batch_filenames.append(img["filename"])
                                    batch_task_ids.append(img.get("taskId"))
                                
                                print(f"[WS] Collected {len(batch_images)} images for batch {batch_id_for_task}, taskIds: {batch_task_ids}, expected: {expected_count}")
                                
                                # Verify we have all expected images
                                if len(batch_images) != expected_count:
                                    print(f"[WS] WARNING: Expected {expected_count} images but collected {len(batch_images)}!")
                                
                                if len(batch_images) > 0:
                                    # Send batch_queued
                                    if not batch_state[batch_id_for_task]["queued_sent"]:
                                        try:
                                            # Create zip file when first batch starts processing
                                            if zip_state["file"] is None:
                                                await create_zip_file()
                                            
                                            await websocket.send_json({
                                                "type": "batch_queued",
                                                "batchId": batch_id_for_task,
                                                "message": f"Batch {batch_id_for_task} processing started"
                                            })
                                            batch_state[batch_id_for_task]["queued_sent"] = True
                                            print(f"[WS] Sent batch_queued for batch {batch_id_for_task}")
                                        except Exception as e:
                                            print(f"[WS] Error sending batch_queued: {str(e)}")
                                    
                                    # Start processing immediately
                                    batch_state[batch_id_for_task]["processing"] = True
                                    
                                    # Use the same send_result_callback and process_batch functions
                                    # (defined in batch_end handler, but we'll define them here too)
                                    async def send_result_callback_inline(result_dict):
                                        """Callback to send individual results as they complete"""
                                        nonlocal total_images_processed, total_images_expected, all_batches_complete
                                        
                                        if connection_state['closed']:
                                            return
                                        
                                        batch_id_cb = result_dict.get("batchId")
                                        task_id = result_dict.get("taskId")
                                        output_bytes = result_dict.get("_image_data")
                                        image_id = result_dict.get("_imageId")
                                        output_filename = result_dict.get("filename")
                                        mime_type = result_dict.get("mimeType")
                                        save_format = result_dict.get("format")
                                        
                                        print(f"[WS] Inline callback received for batch {batch_id_cb}, task {task_id}, image_id: {image_id}, filename: {output_filename}, has_data: {output_bytes is not None}")
                                        
                                        if not output_bytes or not image_id:
                                            print(f"[WS] WARNING: Skipping image - output_bytes: {output_bytes is not None}, image_id: {image_id}")
                                            return
                                        
                                        image_url = None
                                        if config.get('returnBase64', True):
                                            image_base64 = base64.b64encode(output_bytes).decode('utf-8')
                                            image_url = f"data:{mime_type};base64,{image_base64}"
                                        
                                        download_url = f"/api/download?imageId={image_id}"
                                        
                                        if processed_images_store is not None:
                                            processed_images_store[image_id] = {
                                                "data": output_bytes,
                                                "filename": output_filename,
                                                "format": save_format,
                                                "mime_type": mime_type
                                            }
                                        
                                        # Add to zip file immediately (use unique filename to avoid overwrites)
                                        unique_filename = f"{task_id}_{output_filename}" if task_id is not None else f"{image_id}_{output_filename}"
                                        try:
                                            await add_to_zip(image_id, output_bytes, unique_filename)
                                        except Exception as zip_error:
                                            print(f"[WS] CRITICAL: Failed to add image {image_id} (task {task_id}) to zip: {str(zip_error)}")
                                            # Don't continue if zip add fails - this is critical
                                            raise
                                        
                                        await websocket.send_json({
                                            "type": "image_processed",
                                            "batchId": batch_id_cb,
                                            "taskId": task_id,
                                            "filename": output_filename,
                                            "downloadUrl": download_url,
                                            "imageId": image_id,
                                            "format": save_format,
                                            "mimeType": mime_type,
                                            "success": True,
                                            **({"imageUrl": image_url} if image_url else {})
                                        })
                                        
                                        total_images_processed += 1
                                        print(f"[WS] Progress: {total_images_processed}/{total_images_expected} processed, {zip_state['images_added']}/{total_images_expected} added to zip")
                                        
                                        if batch_id_cb in batch_counters:
                                            batch_counters[batch_id_cb]["done"] += 1
                                            if (batch_counters[batch_id_cb]["done"] >= batch_counters[batch_id_cb]["total"] 
                                                and not connection_state['closed']):
                                                try:
                                                    await websocket.send_json({
                                                        "type": "batch_complete",
                                                        "batchId": batch_id_cb,
                                                        "message": f"Batch {batch_id_cb} processing completed"
                                                    })
                                                except Exception as e:
                                                    print(f"[WS] Error sending batch_complete: {str(e)}")
                                        
                                        if (total_images_processed >= total_images_expected and 
                                            total_images_expected > 0 and
                                            zip_state["images_added"] >= total_images_expected):
                                            if not all_batches_complete:
                                                all_batches_complete = True
                                                print(f"[WS] All {total_images_processed} images processed and {zip_state['images_added']} added to zip, finalizing...")
                                                zip_path = await finalize_zip()
                                                zip_id = os.path.basename(zip_path).replace('.zip', '') if zip_path else None
                                                if zip_id and processed_images_store is not None:
                                                    processed_images_store[f"zip_{zip_id}"] = {
                                                        "data": None,
                                                        "filename": f"processed_images_{zip_id}.zip",
                                                        "format": "ZIP",
                                                        "mime_type": "application/zip",
                                                        "file_path": zip_path
                                                    }
                                                
                                                if not connection_state['closed']:
                                                    try:
                                                        all_complete_msg = {
                                                            "type": "all_complete",
                                                            "message": "All images processed",
                                                            "zipDownloadUrl": f"/api/download?imageId=zip_{zip_id}" if zip_id else None,
                                                            "totalProcessed": total_images_processed,
                                                            "totalImages": zip_state["images_added"]  # Total images in zip (includes pre-uploaded)
                                                        }
                                                        print(f"[WS] Sending all_complete (inline): totalProcessed={total_images_processed}, totalImages={zip_state['images_added']}, zip_id={zip_id}")
                                                        await websocket.send_json(all_complete_msg)
                                                    except Exception as e:
                                                        print(f"[WS] Error sending all_complete: {str(e)}")
                                    
                                    async def process_batch_inline():
                                        try:
                                            print(f"[WS] Starting batch {batch_id_for_task} processing with {len(batch_images)} images")
                                            await process_batch_async(
                                                batch_id_for_task,
                                                batch_images,
                                                config['backgroundColor'],
                                                config['fileType'],
                                                config['watermark'],
                                                batch_filenames,
                                                send_result_callback_inline,
                                                None
                                            )
                                            print(f"[WS] Batch {batch_id_for_task} processing completed")
                                        except Exception as e:
                                            print(f"[WS] Error processing batch {batch_id_for_task}: {str(e)}")
                                            import traceback
                                            traceback.print_exc()
                                    
                                    batch_task = asyncio.create_task(process_batch_inline())
                                    active_tasks.append(batch_task)
                                    
                                    # Clear pending images for this batch
                                    pending_images = [img for img in pending_images if img.get("batchId") != batch_id_for_task]
                                    current_batch_id = batch_id_for_task + 1
            
            elif message.get("type") == "websocket.disconnect":
                print(f"[WS] WebSocket disconnect message received")
                connection_state['closed'] = True
                break
        
        # Wait for active tasks to complete before closing
        if active_tasks:
            print(f"[WS] Waiting for {len(active_tasks)} active processing tasks to complete...")
            await asyncio.gather(*active_tasks, return_exceptions=True)
            print(f"[WS] All processing tasks completed")
                
    except WebSocketDisconnect:
        print(f"[WS] WebSocket disconnected (exception)")
        connection_state['closed'] = True
    except Exception as e:
        print(f"[WS] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        try:
            if not connection_state['closed']:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
        except:
            pass
    finally:
        connection_state['closed'] = True
        if connection_id in _websocket_connections:
            del _websocket_connections[connection_id]
        print(f"[WS] Connection {connection_id} closed")