"""Background workers for GPU processing and batch management"""
import asyncio
import torch
from concurrent.futures import ThreadPoolExecutor
from gpu_manager import NUM_GPUS
from image_processor import process_image_sync, process_batch_sync
from storage import store_image

# Thread pool for CPU-bound operations - limit to prevent GPU memory exhaustion
# Thread pool for CPU-bound operations
# rembg sessions can be reused for batch processing, but we still limit workers for stability
MAX_WORKERS = min(16, NUM_GPUS * 4) if NUM_GPUS > 0 else 4
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
print(f"Thread pool configured with {MAX_WORKERS} workers")

# Semaphore to limit concurrent GPU operations per GPU
# rembg sessions are more stable than transparent_background, but we still limit concurrency
# This prevents GPU memory issues and ensures stable batch processing
_gpu_semaphores = {}
for gpu_id in range(NUM_GPUS):
    _gpu_semaphores[gpu_id] = asyncio.Semaphore(1)  # Only 1 concurrent operation per GPU (thread-safety)
print(f"Initialized {len(_gpu_semaphores)} GPU semaphores (max 1 concurrent operation per GPU for thread-safety)")

# Queue system for continuous processing (keeps GPU always busy)
_processing_queue = asyncio.Queue()
_gpu_worker_tasks = []  # Background worker tasks for each GPU

# Batch pipeline system for overlapping upload/processing
_batch_queue = asyncio.Queue()  # Queue of batches waiting to be processed
_current_batch_processing = None  # Current batch being processed
_batch_processing_lock = asyncio.Lock()  # Lock for batch processing


def get_executor():
    """Get the thread pool executor"""
    return _executor


def get_gpu_semaphores():
    """Get GPU semaphores"""
    return _gpu_semaphores


def get_processing_queue():
    """Get the processing queue"""
    return _processing_queue


def get_batch_queue():
    """Get the batch queue"""
    return _batch_queue


def get_batch_processing_lock():
    """Get the batch processing lock"""
    return _batch_processing_lock


def get_current_batch_processing():
    """Get current batch being processed"""
    return _current_batch_processing


def set_current_batch_processing(batch_id):
    """Set current batch being processed"""
    global _current_batch_processing
    _current_batch_processing = batch_id


# Background worker for continuous GPU processing (keeps GPU always busy)
async def gpu_worker(gpu_id: int):
    """Background worker that continuously processes images from queue for a specific GPU"""
    while True:
        try:
            # Get next image from queue (blocks until available)
            task_data = await _processing_queue.get()
            
            if task_data is None:  # Shutdown signal
                break
            
            task_id, image_data, filename, bg_color, output_format, watermark_option, callback = task_data
            
            try:
                # Process image with this GPU
                processed_image_bytes, mime_type, processed_filename, output_format_final = await asyncio.get_event_loop().run_in_executor(
                    _executor,
                    process_image_sync,
                    image_data,
                    bg_color,
                    output_format,
                    watermark_option,
                    filename,
                    gpu_id
                )
                
                # Store processed image
                image_id = f"img_{task_id}"
                store_image(image_id, processed_image_bytes, processed_filename, output_format_final, mime_type)
                
                # Send result immediately via callback
                download_url = f"/api/download?imageId={image_id}"
                result = {
                    "taskId": task_id,
                    "imageId": image_id,
                    "downloadUrl": download_url,
                    "filename": processed_filename,
                    "format": output_format_final,
                    "mimeType": mime_type,
                    "success": True
                }
                
                if callback:
                    await callback(result)
                
            except Exception as e:
                import traceback
                error_msg = f"Error processing image {task_id} ({filename}): {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                
                # If it's a CUDA illegal memory access, reset the GPU
                error_str = str(e)
                if "illegal memory access" in error_str.lower() or "cudaErrorIllegalAddress" in error_str:
                    print(f"CUDA illegal memory access in worker for GPU {gpu_id}, GPU will be reset on next get_remover call")
                    # The GPU will be reset automatically on next get_remover call
                    # due to the reset_gpu function in image_processor
                
                # Send error via callback
                result = {
                    "taskId": task_id,
                    "filename": filename,
                    "success": False,
                    "error": error_msg
                }
                
                if callback:
                    await callback(result)
            
            finally:
                # Mark task as done
                _processing_queue.task_done()
                
        except Exception as e:
            print(f"Error in GPU worker {gpu_id}: {e}")
            await asyncio.sleep(0.1)  # Small delay on error


# Batch processor - processes batches sequentially but allows next batch to upload while processing
async def batch_processor():
    """Processes batches sequentially - while one batch processes, next batch can be uploaded"""
    global _current_batch_processing
    
    while True:
        try:
            # Get next batch from queue (blocks until available)
            batch_data = await _batch_queue.get()
            
            if batch_data is None:  # Shutdown signal
                break
            
            batch_id, batch_images, bg_color, output_format, watermark_option, callback = batch_data
            
            async with _batch_processing_lock:
                _current_batch_processing = batch_id
                print(f"Starting processing batch {batch_id} ({len(batch_images)} images)")
            
            try:
                # Process all images in batch (distributed across GPUs)
                # Create completion tracker for this batch
                batch_completion = {"count": 0, "total": len(batch_images)}
                batch_completion_event = asyncio.Event()
                
                async def individual_callback(result):
                    """Callback for individual image that tracks batch completion"""
                    # Call the batch callback
                    await callback(result)
                    batch_completion["count"] += 1
                    # If all images in batch are done, signal completion
                    if batch_completion["count"] >= batch_completion["total"]:
                        batch_completion_event.set()
                
                # Add all images to processing queue (GPU workers will process in parallel)
                for task_id, image_data, filename in batch_images:
                    await _processing_queue.put((
                        task_id,
                        image_data,
                        filename,
                        bg_color,
                        output_format,
                        watermark_option,
                        individual_callback  # Individual callback for each image
                    ))
                
                print(f"Batch {batch_id} queued for processing ({len(batch_images)} images)")
                
                # Wait for all images in batch to complete
                # This ensures batches are processed sequentially (pipeline workflow)
                await batch_completion_event.wait()
                print(f"Batch {batch_id} processing complete")
                
            except Exception as e:
                import traceback
                print(f"Error processing batch {batch_id}: {e}")
                print(traceback.format_exc())
            
            finally:
                async with _batch_processing_lock:
                    _current_batch_processing = None
                _batch_queue.task_done()
                
        except Exception as e:
            print(f"Error in batch processor: {e}")
            await asyncio.sleep(0.1)


async def start_workers():
    """Start background GPU workers and batch processor"""
    global _gpu_worker_tasks
    if NUM_GPUS > 0:
        # Start GPU workers
        for gpu_id in range(NUM_GPUS):
            task = asyncio.create_task(gpu_worker(gpu_id))
            _gpu_worker_tasks.append(task)
        print(f"Started {NUM_GPUS} GPU worker(s) for continuous processing")
        
        # Start batch processor
        batch_processor_task = asyncio.create_task(batch_processor())
        _gpu_worker_tasks.append(batch_processor_task)
        print("Started batch processor for pipeline workflow")


async def stop_workers():
    """Stop background GPU workers"""
    global _gpu_worker_tasks
    # Send shutdown signal to all workers
    for _ in range(NUM_GPUS):
        await _processing_queue.put(None)
    await _batch_queue.put(None)  # Signal batch processor to stop
    # Wait for workers to finish
    if _gpu_worker_tasks:
        await asyncio.gather(*_gpu_worker_tasks, return_exceptions=True)

