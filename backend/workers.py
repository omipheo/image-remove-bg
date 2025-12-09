"""
Workers for batch processing with model pooling
"""
import asyncio
from typing import List, Callable, Optional
from PIL import Image
import io
from image_processor import process_image_sync, initialize_model_pool
import time

# Global batch queue
_batch_queue = asyncio.Queue()
_batch_processor_started = False

def get_batch_queue():
    return _batch_queue

def start_batch_processor():
    """Initialize the batch processor (currently using model pool instead of separate processor)"""
    global _batch_processor_started
    if not _batch_processor_started:
        # Initialize model pool for batch processing
        initialize_model_pool()
        _batch_processor_started = True
        print("[BATCH_PROCESSOR] Batch processor initialized with model pool")

async def process_batch_async(
    batch_id: int,
    image_data_list: List[bytes],
    background_color: str,
    file_type: str,
    watermark: str,
    filenames: List[str],
    result_callback: Callable,
    gpu_id: Optional[int] = None
):
    """
    Process a batch of images using pre-loaded model pool.
    
    Key changes:
    - High concurrency (10 images at once across 4 GPUs)
    - Uses pre-loaded models (no OOM)
    - Fast processing
    """
    import torch
    
    print(f"[WORKER] Starting batch {batch_id} with {len(image_data_list)} images")
    
    # Get number of GPUs
    NUM_GPUS = torch.cuda.device_count() if torch.cuda.is_available() else 1
    print(f"[WORKER] Using {NUM_GPUS} GPU(s)")
    
    # Semaphore to limit concurrent processing (2-3 per GPU = 8-12 total for 4 GPUs)
    max_concurrent = NUM_GPUS * 2  # 2 images per GPU concurrently
    semaphore = asyncio.Semaphore(max_concurrent)
    
    # Counter for round-robin GPU assignment
    gpu_counter = 0
    
    async def process_single_image(idx: int, image_bytes: bytes, filename: str):
        nonlocal gpu_counter
        
        async with semaphore:
            # Assign GPU in round-robin fashion
            assigned_gpu = gpu_counter % NUM_GPUS
            gpu_counter += 1
            
            try:
                print(f"[WORKER] Processing image {idx} on GPU {assigned_gpu}: {filename}")
                start_time = time.time()
                
                # Run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result_tuple = await loop.run_in_executor(
                    None,
                    process_image_sync,
                    image_bytes,
                    background_color,
                    file_type,
                    watermark,
                    filename,
                    assigned_gpu  # Use assigned GPU
                )
                
                elapsed = time.time() - start_time
                
                # Unpack tuple: (output_bytes, mime_type, output_filename, save_format)
                output_bytes, mime_type, output_filename, save_format = result_tuple
                
                # Convert to base64 for WebSocket transmission
                import base64
                import uuid
                image_base64 = base64.b64encode(output_bytes).decode('utf-8')
                image_url = f"data:{mime_type};base64,{image_base64}"
                image_id = f"img_{uuid.uuid4().hex[:12]}"
                download_url = f"/api/download?imageId={image_id}"
                
                # Create result dict with batch and task metadata
                result = {
                    "batchId": batch_id,
                    "taskId": idx,
                    "filename": output_filename,
                    "imageUrl": image_url,
                    "downloadUrl": download_url,
                    "imageId": image_id,
                    "format": save_format,
                    "mimeType": mime_type,
                    "_image_data": output_bytes,
                    "_image_id": image_id,
                    "success": True
                }
                
                print(f"[WORKER] Image {idx} completed on GPU {assigned_gpu} in {elapsed:.2f}s")
                
                # Send result via callback
                if result_callback:
                    await result_callback(result)
                
                return result
                
            except Exception as e:
                print(f"[WORKER] Error processing image {idx}: {str(e)}")
                import traceback
                traceback.print_exc()
                
                # Send error result
                error_result = {
                    "batchId": batch_id,
                    "taskId": idx,
                    "filename": filename,
                    "error": str(e),
                    "success": False
                }
                
                if result_callback:
                    try:
                        await result_callback(error_result)
                    except Exception as callback_error:
                        print(f"[WORKER] Error in callback: {str(callback_error)}")
                
                return error_result
    
    # Process all images concurrently (limited by semaphore)
    batch_start = time.time()
    tasks = [
        process_single_image(idx, img_data, filenames[idx])
        for idx, img_data in enumerate(image_data_list)
    ]
    
    # Wait for all to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    batch_elapsed = time.time() - batch_start
    print(f"[WORKER] Batch {batch_id} completed in {batch_elapsed:.2f}s, processed {len(results)} images")
    
    return results