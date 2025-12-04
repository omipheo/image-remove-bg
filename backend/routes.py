"""API routes for image processing endpoints"""
import base64
import asyncio
import json
import time
import io
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from PIL import Image
from typing import Optional

from image_processor import process_image_sync
from storage import store_image, get_image, get_latest_image
from workers import (
    get_executor, get_gpu_semaphores, get_processing_queue, get_batch_queue,
    get_batch_processing_lock, get_current_batch_processing, set_current_batch_processing
)
from gpu_manager import NUM_GPUS
import torch

router = APIRouter()


@router.get("/")
async def root():
    return {"message": "Image Background Removal API", "status": "running"}


@router.post("/api/upload")
async def upload_image(request: Request):
    """
    Upload an image and remove its background.
    Returns the processed image as base64 or URL.
    
    Parameters:
    - backgroundColor: "transparent", "white", or "black"
    - fileType: "PNG" or "JPEG"
    """
    try:
        # Parse form data manually to handle optional fields
        form_data = await request.form()
        
        # Get file from form data
        file = form_data.get("image")
        if not file:
            print("DEBUG: No file found in form_data")
            print(f"DEBUG: form_data keys: {list(form_data.keys())}")
            raise HTTPException(status_code=400, detail="Image file is required")
        
        # Check if it's an UploadFile instance (can be FastAPI's UploadFile or Starlette's)
        if not isinstance(file, (UploadFile, StarletteUploadFile)):
            # Check if it has the required attributes instead
            if not hasattr(file, 'read') or not hasattr(file, 'content_type'):
                raise HTTPException(status_code=400, detail="Invalid file type")
        
        # Get optional parameters with defaults
        backgroundColor = form_data.get("backgroundColor", "white")
        fileType = form_data.get("fileType", "JPEG")
        watermark = form_data.get("watermark", "none")
        
        # Normalize and validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "white"
        output_format = fileType.upper() if fileType else "JPEG"
        watermark_option = watermark.lower() if watermark else "none"
        
        # Validate file type
        if not hasattr(file, 'content_type') or not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Validate parameters
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(status_code=400, detail="backgroundColor must be 'transparent', 'white', or 'black'")
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(status_code=400, detail="fileType must be 'PNG' or 'JPEG'")
        
        if watermark_option not in ["none", "blog"]:
            raise HTTPException(status_code=400, detail="watermark must be 'none' or 'blog'")
        
        # Read image file
        image_data = await file.read()
        filename = getattr(file, 'filename', 'processed_image') or 'processed_image'
        
        # Process the image using helper function
        loop = asyncio.get_event_loop()
        executor = get_executor()
        processed_image_bytes, mime_type, processed_filename, output_format = await loop.run_in_executor(
            executor,
            process_image_sync,
            image_data,
            bg_color,
            output_format,
            watermark_option,
            filename,
            None  # GPU ID will be assigned via round-robin
        )
        
        # Convert to base64 for frontend
        print("Encoding to base64...")
        image_base64 = base64.b64encode(processed_image_bytes).decode("utf-8")
        print(f"Base64 encoded size: {len(image_base64)} characters")
        image_url = f"data:{mime_type};base64,{image_base64}"
        print("Image processing completed, returning response")
        
        # Store the processed image (in production, use proper storage)
        from storage import processed_images
        image_id = f"img_{len(processed_images)}"
        store_image(image_id, processed_image_bytes, processed_filename, output_format, mime_type)
        
        return {
            "imageUrl": image_url,
            "imageId": image_id,
            "message": "Background removed successfully"
        }
        
    except HTTPException as e:
        print(f"HTTPException: {e.detail}")
        raise
    except Exception as e:
        import traceback
        print(f"Error details: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


@router.post("/api/upload-batch")
async def upload_images_batch(request: Request):
    """
    Upload multiple images and remove their backgrounds in a single request.
    Returns an array of processed images.
    
    Parameters:
    - images: Multiple image files (form field name: "images")
    - backgroundColor: "transparent", "white", or "black"
    - fileType: "PNG" or "JPEG"
    """
    try:
        print("DEBUG: Batch upload endpoint called")
        # Parse form data
        form_data = await request.form()
        
        print(f"DEBUG: form_data keys: {list(form_data.keys())}")
        
        # Get files from form data (multiple files with same field name)
        # In Starlette/FastAPI, getlist() returns a list of values for the key
        files = form_data.getlist("images")
        print(f"DEBUG: Found {len(files) if files else 0} files")
        
        if not files or len(files) == 0:
            print("DEBUG: No files found in form_data")
            raise HTTPException(status_code=400, detail="At least one image file is required")
        
        # Get optional parameters with defaults
        backgroundColor = form_data.get("backgroundColor", "white")
        fileType = form_data.get("fileType", "JPEG")
        watermark = form_data.get("watermark", "none")
        
        # Normalize and validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "white"
        output_format = fileType.upper() if fileType else "JPEG"
        watermark_option = watermark.lower() if watermark else "none"
        
        # Validate parameters
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(status_code=400, detail="backgroundColor must be 'transparent', 'white', or 'black'")
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(status_code=400, detail="fileType must be 'PNG' or 'JPEG'")
        
        if watermark_option not in ["none", "blog"]:
            raise HTTPException(status_code=400, detail="watermark must be 'none' or 'blog'")
        
        # Validate all files are images
        for file in files:
            if not isinstance(file, (UploadFile, StarletteUploadFile)):
                if not hasattr(file, 'read') or not hasattr(file, 'content_type'):
                    raise HTTPException(status_code=400, detail="Invalid file type")
            if not hasattr(file, 'content_type') or not file.content_type or not file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="All files must be images")
        
        print(f"Processing batch of {len(files)} images in parallel")
        start_time = time.time()
        
        # Read all files first (I/O bound, can be parallelized)
        async def read_file_data(file, idx):
            if hasattr(file, 'read'):
                image_data = await file.read()
                filename = getattr(file, 'filename', f'image_{idx}') or f'image_{idx}'
            else:
                image_data = file
                filename = f'image_{idx}'
            return image_data, filename, file
        
        # Read all files in parallel
        file_data_tasks = [read_file_data(file, idx) for idx, file in enumerate(files)]
        file_data_list = await asyncio.gather(*file_data_tasks)
        
        # Process all images in parallel using asyncio.gather with GPU load balancing
        # rembg sessions support batch processing and are more stable than transparent_background
        # We still limit concurrency per GPU for stability
        CHUNK_SIZE = 108  # Process 24 images per chunk (matches recommended frontend batch size)
        
        executor = get_executor()
        gpu_semaphores = get_gpu_semaphores()
        
        async def process_with_index(image_data, filename, original_file, idx):
            try:
                # Distribute images across GPUs using round-robin
                gpu_id = idx % NUM_GPUS if NUM_GPUS > 0 else None
                
                # Use semaphore to limit concurrent GPU operations
                if gpu_id is not None and NUM_GPUS > 0:
                    async with gpu_semaphores[gpu_id]:
                        # Process the image directly using the sync function in thread pool
                        loop = asyncio.get_event_loop()
                        processed_image_bytes, mime_type, processed_filename, output_format_final = await loop.run_in_executor(
                            executor,
                            process_image_sync,
                            image_data,
                            bg_color,
                            output_format,
                            watermark_option,
                            filename,
                            gpu_id  # Pass GPU ID for load balancing
                        )
                else:
                    # CPU mode - no semaphore needed
                    loop = asyncio.get_event_loop()
                    processed_image_bytes, mime_type, processed_filename, output_format_final = await loop.run_in_executor(
                        executor,
                        process_image_sync,
                        image_data,
                        bg_color,
                        output_format,
                        watermark_option,
                        filename,
                        gpu_id
                    )
                
                # Store the processed image (don't base64 encode for batch - too large!)
                from storage import processed_images
                image_id = f"img_{len(processed_images) + idx}"
                store_image(image_id, processed_image_bytes, processed_filename, output_format_final, mime_type)
                
                # Return only image ID and download URL - frontend will download separately
                # This prevents massive response sizes (100 images = 50-200MB if base64)
                download_url = f"/api/download?imageId={image_id}"
                
                return {
                    "imageId": image_id,
                    "downloadUrl": download_url,
                    "filename": processed_filename,
                    "format": output_format_final,
                    "mimeType": mime_type
                }
            except Exception as e:
                import traceback
                error_msg = f"Error processing image {idx + 1} ({filename}): {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                return {
                    "error": error_msg,
                    "filename": filename
                }
        
        # Process images in chunks to avoid memory issues with large batches
        results = []
        total_files = len(file_data_list)
        
        for chunk_start in range(0, total_files, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total_files)
            chunk_data = file_data_list[chunk_start:chunk_end]
            
            print(f"Processing chunk {chunk_start//CHUNK_SIZE + 1}/{(total_files-1)//CHUNK_SIZE + 1} ({chunk_end - chunk_start} images)")
            
            # Process chunk in parallel (limited concurrency)
            processing_tasks = [
                process_with_index(image_data, filename, original_file, chunk_start + idx)
                for idx, (image_data, filename, original_file) in enumerate(chunk_data)
            ]
            chunk_results = await asyncio.gather(*processing_tasks)
            results.extend(chunk_results)
            
            # Clear GPU cache between chunks to free up memory and prevent corruption
            if NUM_GPUS > 0:
                for gpu_id in range(NUM_GPUS):
                    try:
                        with torch.cuda.device(gpu_id):
                            torch.cuda.synchronize()  # Wait for all operations to complete
                            torch.cuda.empty_cache()  # Free unused memory
                            # Force garbage collection to help with memory cleanup
                            import gc
                            gc.collect()
                    except Exception as e:
                        print(f"Warning: Could not clear cache for GPU {gpu_id}: {e}")
            
            # Longer delay between chunks to allow memory to free up and prevent corruption
            if chunk_end < total_files:
                await asyncio.sleep(2.0)  # Increased delay for memory cleanup and stability
                # Additional GPU reset check - if many errors occurred, reset GPUs
                chunk_errors = len([r for r in chunk_results if 'error' in r])
                if chunk_errors > chunk_end - chunk_start * 0.5:  # More than 50% errors
                    print(f"High error rate detected ({chunk_errors}/{chunk_end - chunk_start}), resetting all GPUs...")
                    from gpu_manager import reset_all_gpus
                    reset_all_gpus()
                    await asyncio.sleep(1.0)  # Additional delay after reset
        
        elapsed_time = time.time() - start_time
        successful = len([r for r in results if 'error' not in r])
        failed = len([r for r in results if 'error' in r])
        print(f"Batch processing completed in {elapsed_time:.2f}s: {successful} successful, {failed} failed ({len(files)/elapsed_time:.2f} images/sec)")
        
        return {
            "results": results,
            "total": len(files),
            "successful": len([r for r in results if 'error' not in r]),
            "failed": len([r for r in results if 'error' in r])
        }
        
    except HTTPException as e:
        print(f"HTTPException: {e.detail}")
        raise
    except Exception as e:
        import traceback
        print(f"Error details: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error processing batch: {str(e)}")


@router.get("/api/download")
async def download_image(imageId: str = None, fileType: str = None):
    """
    Download the processed image.
    If imageId is provided, returns that specific image.
    Otherwise, returns the most recently processed image.
    
    Parameters:
    - imageId: ID of the image to download
    - fileType: Optional override for file type ("PNG" or "JPEG")
    """
    try:
        image_data = None
        
        if imageId:
            image_data = get_image(imageId)
        
        if not image_data:
            image_data = get_latest_image()
        
        if not image_data:
            raise HTTPException(status_code=404, detail="No processed image found")
        
        # If fileType is specified, convert the image
        if fileType and fileType.upper() in ["PNG", "JPEG"]:
            output_format = "PNG" if fileType.upper() == "PNG" else "JPEG"
            mime_type = "image/png" if output_format == "PNG" else "image/jpeg"
            
            # Load the stored image
            stored_image = Image.open(io.BytesIO(image_data["data"]))
            
            # Convert format if needed
            if output_format == "JPEG" and stored_image.mode == "RGBA":
                # Convert RGBA to RGB with white background for JPEG
                rgb_image = Image.new("RGB", stored_image.size, (255, 255, 255))
                rgb_image.paste(stored_image, mask=stored_image.split()[3])
                stored_image = rgb_image
            
            # Convert to bytes
            img_byte_arr = io.BytesIO()
            stored_image.save(img_byte_arr, format=output_format, quality=95)
            img_byte_arr.seek(0)
            image_bytes = img_byte_arr.read()
            
            # Update filename extension
            filename = image_data["filename"].rsplit('.', 1)[0]
            extension = "png" if output_format == "PNG" else "jpg"
            filename = f"{filename}.{extension}"
        else:
            # Use stored format
            image_bytes = image_data["data"]
            mime_type = image_data.get("mime_type", "image/png")
            filename = image_data["filename"]
        
        return Response(
            content=image_bytes,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading image: {str(e)}")


@router.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@router.websocket("/ws/process-images")
async def websocket_process_images(websocket: WebSocket):
    """WebSocket endpoint for batch-based pipeline processing (upload while processing)"""
    await websocket.accept()
    
    task_counter = 0
    batch_counter = 0
    current_batch_images = []  # Current batch being uploaded
    batch_completion_trackers = {}  # Track batch completion: {batch_id: {total, completed, results}}
    
    try:
        # Receive configuration first
        config_data = await websocket.receive_json()
        bg_color = config_data.get("backgroundColor", "white")
        output_format = config_data.get("fileType", "JPEG")
        watermark_option = config_data.get("watermark", "none")
        batch_size = config_data.get("batchSize", 20)  # Default batch size
        
        print(f"WebSocket connection established. Config: bg={bg_color}, format={output_format}, watermark={watermark_option}, batchSize={batch_size}")
        
        async def send_result(result):
            """Callback to send result via WebSocket"""
            await websocket.send_json(result)
        
        batch_queue = get_batch_queue()
        
        # Process batches in pipeline (upload next batch while processing current batch)
        while True:
            # Receive message
            message = await websocket.receive()
            
            if message["type"] == "websocket.disconnect":
                break
            
            if message["type"] == "websocket.receive":
                if "text" in message:
                    data = json.loads(message["text"])
                    
                    if data.get("type") == "batch_start":
                        # Start of a new batch
                        batch_id = batch_counter
                        batch_counter += 1
                        current_batch_images = []
                        batch_completion_trackers[batch_id] = {
                            "total": data.get("batchSize", batch_size),
                            "completed": 0,
                            "results": []
                        }
                        
                        print(f"Batch {batch_id} upload started ({data.get('batchSize', batch_size)} images)")
                        
                        await websocket.send_json({
                            "type": "batch_started",
                            "batchId": batch_id
                        })
                    
                    elif data.get("type") == "image_metadata":
                        # Metadata for next image in current batch
                        filename = data.get("filename", f"image_{task_counter}.jpg")
                        task_id = data.get("taskId", task_counter)
                        task_counter = max(task_counter, task_id + 1)
                        
                        # Wait for binary image data
                        binary_message = await websocket.receive()
                        
                        if binary_message["type"] == "websocket.receive" and "bytes" in binary_message:
                            image_data = binary_message["bytes"]
                            
                            # Add to current batch
                            current_batch_images.append((task_id, image_data, filename))
                            
                            await websocket.send_json({
                                "type": "image_received",
                                "taskId": task_id,
                                "filename": filename
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "taskId": task_id,
                                "message": "Expected binary image data"
                            })
                    
                    elif data.get("type") == "batch_end":
                        # End of batch upload - start processing this batch
                        batch_id = data.get("batchId", batch_counter - 1)
                        
                        if batch_id in batch_completion_trackers and current_batch_images:
                            print(f"Batch {batch_id} upload complete ({len(current_batch_images)} images). Starting processing...")
                            
                            # Create completion tracker for this batch
                            batch_tracker = batch_completion_trackers[batch_id]
                            batch_tracker["total"] = len(current_batch_images)
                            
                            async def batch_result_callback(result):
                                """Callback for batch results"""
                                batch_tracker["completed"] += 1
                                batch_tracker["results"].append(result)
                                
                                # Send individual result
                                await send_result(result)
                                
                                # Debug: Log progress
                                print(f"Batch {batch_id} progress: {batch_tracker['completed']}/{batch_tracker['total']}")
                                
                                # If batch complete, send batch completion message
                                if batch_tracker["completed"] >= batch_tracker["total"]:
                                    successful = len([r for r in batch_tracker["results"] if r.get("success", False)])
                                    failed = len([r for r in batch_tracker["results"] if not r.get("success", False)])
                                    print(f"Batch {batch_id} complete: {successful} successful, {failed} failed. Sending batch_complete message...")
                                    await websocket.send_json({
                                        "type": "batch_complete",
                                        "batchId": batch_id,
                                        "total": batch_tracker["total"],
                                        "successful": successful,
                                        "failed": failed
                                    })
                                    print(f"Batch {batch_id} processing complete - batch_complete message sent")
                            
                            # Add batch to processing queue (will be processed sequentially)
                            await batch_queue.put((
                                batch_id,
                                current_batch_images,
                                bg_color,
                                output_format,
                                watermark_option,
                                batch_result_callback
                            ))
                            
                            # Clear current batch (ready for next batch upload)
                            current_batch_images = []
                            
                            await websocket.send_json({
                                "type": "batch_queued",
                                "batchId": batch_id,
                                "message": "Batch queued for processing"
                            })
                    
                    elif data.get("type") == "config":
                        # Update configuration
                        if "backgroundColor" in data:
                            bg_color = data["backgroundColor"]
                        if "fileType" in data:
                            output_format = data["fileType"]
                        if "watermark" in data:
                            watermark_option = data["watermark"]
                        if "batchSize" in data:
                            batch_size = data["batchSize"]
                        
                        await websocket.send_json({
                            "type": "config_updated",
                            "backgroundColor": bg_color,
                            "fileType": output_format,
                            "watermark": watermark_option,
                            "batchSize": batch_size
                        })
                    
                    elif data.get("type") == "close":
                        break
    
    except WebSocketDisconnect:
        print("WebSocket client disconnected")
    except Exception as e:
        import traceback
        print(f"WebSocket error: {e}")
        print(traceback.format_exc())
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass

