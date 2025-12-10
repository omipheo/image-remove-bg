"""
Workers for batch processing with model pooling
"""
import asyncio
import logging
from typing import List, Callable, Optional
from PIL import Image
import io
import base64
from image_processor import process_image_sync, initialize_model_pool
from gpu_manager import NUM_GPUS
import time

logger = logging.getLogger(__name__)

# Global batch queue
_batch_queue = asyncio.Queue()
_batch_processor_started = False
# OPTIMIZATION: Increase concurrency for 4x RTX 3090
_processing_semaphore = asyncio.Semaphore(max(1, NUM_GPUS * 8))  # Increased from *3 to *8

def get_processing_semaphore():
    return _processing_semaphore

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


async def process_batch_parallel(batch_images, batch_id, config, callback):
    """
    Process batch of images in parallel across GPUs - OPTIMIZED for 4x RTX 3090
    
    Args:
        batch_images: dict of {task_id: {'image': PIL.Image, 'filename': str, 'task_id': int, 'batch_id': int}}
        batch_id: int
        config: dict with backgroundColor, fileType, watermark
        callback: async function to call with each result
    
    Returns:
        List of results
    """
    logger.info(f"[WORKER] Starting batch {batch_id} with {len(batch_images)} images")
    
    async def process_single_image(task_id, img_data):
        """Process a single image and call callback"""
        try:
            pil_image = img_data['image']
            filename = img_data['filename']
            
            # Validate image
            if not pil_image:
                raise ValueError(f"No image data for task {task_id}")
            
            # Convert PIL image to bytes
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            image_bytes = img_byte_arr.read()
            
            # Validate bytes
            if len(image_bytes) == 0:
                raise ValueError(f"Empty image bytes for task {task_id}")
            
            # Get config
            bg_color = config.get('backgroundColor', 'white')
            file_type = config.get('fileType', 'JPEG')
            watermark = config.get('watermark', 'none')
            
            # Process image using existing GPU function
            logger.debug(f"[WORKER] Processing task {task_id}: {filename}")
            start_time = time.time()
            
            result_tuple = await asyncio.to_thread(
                process_image_sync,
                image_bytes,
                bg_color,
                file_type,
                watermark,
                filename,
                None  # gpu_id=None for round-robin
            )
            
            elapsed = time.time() - start_time
            
            # Unpack result
            output_bytes, mime_type, output_filename, save_format = result_tuple
            
            # Generate image ID
            import uuid
            image_id = f"img_{batch_id}_{task_id}_{int(time.time())}"
            
            # Store the processed image in main.processed_images
            import main
            main.processed_images[image_id] = {
                'data': output_bytes,
                'filename': output_filename,
                'format': save_format,
                'mime_type': mime_type
            }
            
            result = {
                'batch_id': batch_id,
                'task_id': task_id,
                'filename': output_filename,
                'downloadUrl': f'/api/download?imageId={image_id}',
                'imageId': image_id,
                'mime_type': mime_type,
                'format': save_format,
                'success': True
            }
            
            logger.info(f"[WORKER] ✅ Task {task_id} complete in {elapsed:.2f}s: {filename}")
            
            # Send result via callback
            if callback:
                await callback(result)
            
            return result
            
        except Exception as e:
            logger.error(f"[WORKER] ❌ Error processing task {task_id}: {e}", exc_info=True)
            
            error_result = {
                'batch_id': batch_id,
                'task_id': task_id,
                'filename': img_data.get('filename', 'unknown'),
                'success': False,
                'error': str(e)
            }
            
            # Send error via callback
            if callback:
                try:
                    await callback(error_result)
                except Exception as cb_err:
                    logger.error(f"[WORKER] Error in callback: {cb_err}")
            
            return error_result
    
    # Process all images in parallel
    batch_start = time.time()
    
    tasks = [
        process_single_image(task_id, img_data)
        for task_id, img_data in batch_images.items()
    ]
    
    # CRITICAL: Ensure we return the results
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    batch_elapsed = time.time() - batch_start
    success_count = len([r for r in results if isinstance(r, dict) and r.get('success')])
    
    logger.info(f"[WORKER] Batch {batch_id} completed in {batch_elapsed:.2f}s "
               f"({success_count}/{len(results)} successful)")
    
    # CRITICAL: Return the results list
    return results


# Keep the old function for backward compatibility if needed
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
    Legacy batch processing function (kept for backward compatibility)
    """
    logger.info(f"[WORKER] Starting legacy batch {batch_id} with {len(image_data_list)} images")
    
    if NUM_GPUS <= 0:
        raise RuntimeError("No GPUs available for processing")
    
    # Shared semaphore to limit concurrent processing
    semaphore = _processing_semaphore
    
    # Counter for round-robin GPU assignment
    gpu_counter = 0
    
    async def process_single_image(idx: int, image_bytes: bytes, filename: str):
        nonlocal gpu_counter
        
        async with semaphore:
            # Assign GPU in round-robin fashion
            assigned_gpu = gpu_counter % NUM_GPUS
            gpu_counter += 1
            
            try:
                logger.debug(f"[WORKER] Processing image {idx} on GPU {assigned_gpu}: {filename}")
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
                    assigned_gpu
                )
                
                elapsed = time.time() - start_time
                
                # Unpack tuple
                output_bytes, mime_type, output_filename, save_format = result_tuple
                
                # Convert to base64
                import uuid
                image_base64 = base64.b64encode(output_bytes).decode('utf-8')
                image_url = f"data:{mime_type};base64,{image_base64}"
                image_id = f"img_{uuid.uuid4().hex[:12]}"
                
                result = {
                    "batchId": batch_id,
                    "taskId": idx,
                    "filename": output_filename,
                    "imageUrl": image_url,
                    "imageId": image_id,
                    "format": save_format,
                    "mimeType": mime_type,
                    "_image_data": output_bytes,
                    "_imageId": image_id,
                    "success": True
                }
                
                logger.info(f"[WORKER] Image {idx} completed on GPU {assigned_gpu} in {elapsed:.2f}s")
                
                if result_callback:
                    await result_callback(result)
                
                return result
                
            except Exception as e:
                logger.error(f"[WORKER] Error processing image {idx}: {str(e)}", exc_info=True)
                
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
                        logger.error(f"[WORKER] Error in callback: {str(callback_error)}")
                
                return error_result
    
    # Process all images concurrently
    batch_start = time.time()
    tasks = [
        process_single_image(idx, img_data, filenames[idx])
        for idx, img_data in enumerate(image_data_list)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    batch_elapsed = time.time() - batch_start
    logger.info(f"[WORKER] Batch {batch_id} completed in {batch_elapsed:.2f}s")
    
    return results