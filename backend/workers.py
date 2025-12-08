"""
Workers - Background batch processing with GPU support.
Manages concurrent batch processing across multiple GPUs with streaming results.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from gpu_manager import NUM_GPUS
import time

# Worker configuration
MAX_WORKERS = min(32, NUM_GPUS * 8) if NUM_GPUS > 0 else 4
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Semaphores to limit concurrent batch operations per GPU
_gpu_semaphores = {}
for gpu_id in range(NUM_GPUS):
    _gpu_semaphores[gpu_id] = asyncio.Semaphore(4)  # 4 concurrent batches per GPU

# Batch queue
_batch_queue = asyncio.Queue()

async def process_batch_async(batch_id, image_data_list, bg_color, output_format, watermark_option, filenames=None, callback=None, gpu_id=None):
    """
    Process a batch of images asynchronously on GPU with streaming results.
    Processes images individually and calls callback as each completes.
    
    Args:
        batch_id: Batch identifier
        image_data_list: List of image bytes
        bg_color: Background color
        output_format: Output format
        watermark_option: Watermark option
        filenames: List of filenames
        callback: Callback function(result_dict) for each processed image (called immediately)
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        List of results
    """
    import time
    from image_processor import process_image_sync
    from gpu_manager import NUM_GPUS
    import base64
    
    start_time = time.time()
    
    if filenames is None:
        filenames = [f'image_{i}' for i in range(len(image_data_list))]
    
    # Round-robin GPU counter for this batch
    _batch_gpu_counter = 0
    
    # Process images individually for streaming results
    async def process_single_with_callback(idx, image_data, filename):
        """Process single image and call callback immediately"""
        try:
            # Get GPU ID for this image (use provided gpu_id or round-robin)
            nonlocal _batch_gpu_counter
            if gpu_id is not None:
                actual_gpu_id = gpu_id
            elif NUM_GPUS > 0:
                actual_gpu_id = _batch_gpu_counter % NUM_GPUS
                _batch_gpu_counter += 1
            else:
                actual_gpu_id = None
            
            # Process image in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _executor,
                process_image_sync,
                image_data,
                bg_color,
                output_format,
                watermark_option,
                filename,
                actual_gpu_id
            )
            
            if result:
                processed_bytes, mime_type, processed_filename, output_format_final = result
                
                # Prepare result dict (include image data for storage in callback)
                image_id = f"img_{batch_id}_{idx}_{int(time.time() * 1000)}"
                result_dict = {
                    "batchId": batch_id,
                    "taskId": idx,  # Index within batch (0-based)
                    "success": True,
                    "imageId": image_id,
                    "downloadUrl": f"/api/download?imageId={image_id}",
                    "filename": processed_filename,
                    "format": output_format_final,
                    "mimeType": mime_type,
                    "_image_data": processed_bytes,  # Internal: for storage
                    "_image_id": image_id  # Internal: for storage
                }
                
                # Call callback immediately (streaming)
                if callback:
                    try:
                        await callback(result_dict)
                    except Exception as e:
                        print(f"[WORKER] Error in callback for image {idx}: {str(e)}")
                
                return result
            else:
                # Failed
                if callback:
                    try:
                        await callback({
                            "batchId": batch_id,
                            "taskId": idx,
                            "success": False,
                            "error": "Processing failed"
                        })
                    except Exception as e:
                        print(f"[WORKER] Error in callback for failed image {idx}: {str(e)}")
                return None
                
        except Exception as e:
            print(f"[WORKER] Error processing image {idx}: {str(e)}")
            if callback:
                try:
                    await callback({
                        "batchId": batch_id,
                        "taskId": idx,
                        "success": False,
                        "error": str(e)
                    })
                except:
                    pass
            return None
    
    # Process all images concurrently (with semaphore limit)
    max_concurrent = min(10, NUM_GPUS * 2) if NUM_GPUS > 0 else 4
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(idx, image_data, filename):
        async with semaphore:
            return await process_single_with_callback(idx, image_data, filename)
    
    # Process all images concurrently
    tasks = [
        process_with_semaphore(idx, image_data, filenames[idx] if idx < len(filenames) else f'image_{idx}')
        for idx, image_data in enumerate(image_data_list)
    ]
    
    results = await asyncio.gather(*tasks)
    
    elapsed = time.time() - start_time
    successful = len([r for r in results if r is not None])
    failed = len([r for r in results if r is None])
    
    print(f"[WORKER] Batch {batch_id} processed in {elapsed:.2f}s: {successful} successful, {failed} failed ({len(image_data_list)/elapsed:.2f} images/sec)")
    
    return results

async def batch_processor():
    """
    Background worker that processes batches from the queue.
    Processes multiple batches in parallel across GPUs.
    """
    while True:
        try:
            # Get batch from queue
            batch_data = await _batch_queue.get()
            batch_id, batch_images, bg_color, output_format, watermark_option, callback = batch_data
            
            # Process batch immediately in background (non-blocking)
            asyncio.create_task(process_batch_async(
                batch_id,
                batch_images,
                bg_color,
                output_format,
                watermark_option,
                None,  # filenames
                callback,
                None  # gpu_id (round-robin)
            ))
            
            _batch_queue.task_done()  # Allow next batch to be queued
            
        except Exception as e:
            print(f"Error in batch processor: {str(e)}")
            import traceback
            traceback.print_exc()

def get_batch_queue():
    """Get the batch queue for adding batches."""
    return _batch_queue

def start_batch_processor():
    """Start the background batch processor."""
    asyncio.create_task(batch_processor())
