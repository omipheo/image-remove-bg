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
import sys

logger = logging.getLogger(__name__)

# Import main module at module level to ensure we use the same instance
# Use lazy import to avoid circular dependencies
_main_module = None
_processed_images_ref = None

def get_main_module():
    """Get the main module instance, importing it if necessary"""
    global _main_module, _processed_images_ref
    if _main_module is None:
        _main_module = sys.modules.get('main')
        if _main_module is None:
            import main
            _main_module = main
        # Cache the processed_images reference
        _processed_images_ref = _main_module.processed_images
        print(f"[WORKERS] Initialized main module reference: module_id={id(_main_module)}, processed_images_id={id(_processed_images_ref)}")
    return _main_module

def get_processed_images():
    """Get the processed_images dictionary, ensuring we use the same instance"""
    global _processed_images_ref
    if _processed_images_ref is None:
        main_module = get_main_module()
        _processed_images_ref = main_module.processed_images
    return _processed_images_ref

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
            logger.info(f"[WORKER] Processing task {task_id} (batch {batch_id}): {filename} (image size: {len(image_bytes)} bytes)")
            start_time = time.time()
            import hashlib
            input_hash = hashlib.md5(image_bytes[:1024]).hexdigest()
            print(f"[WORKER] Input hash task {task_id}: {input_hash[:8]}… size={len(image_bytes)}")
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
            print(f"[WORKER] Output bytes: {len(output_bytes)}")
            print(f"[WORKER] Mime type: {mime_type}")
            print(f"[WORKER] Output filename: {output_filename}")
            print(f"[WORKER] Save format: {save_format}")

            # Generate image ID
            import uuid
            import hashlib
            image_id = f"img_{batch_id}_{task_id}_{int(time.time())}"
            
            # Calculate hash of output to verify uniqueness
            output_hash = hashlib.md5(output_bytes[:1024]).hexdigest()  # Hash first 1KB for quick check
            # logger.info(f"[WORKER] Task {task_id} processed: {filename} -> {image_id} (output size: {len(output_bytes)} bytes, hash: {output_hash[:8]}...)")
            
            # Store the processed image in main.processed_images
            # Use the cached reference to ensure we use the same dictionary instance
            processed_images_dict = get_processed_images()
            main_module = get_main_module()
            
            print(f"[WORKER] 🔍 Before storing: processed_images has {len(processed_images_dict)} images")
            print(f"[WORKER] 🔍 Storing image_id: {image_id}, filename: {output_filename}")
            print(f"[WORKER] 🔍 Main module id: {id(main_module)}, processed_images id: {id(processed_images_dict)}")
            print(f"[WORKER] 🔍 Cached ref id: {id(_processed_images_ref) if _processed_images_ref else 'None'}")
            
            processed_images_dict[image_id] = {
                'data': output_bytes,
                'filename': output_filename,
                'format': save_format,
                'mime_type': mime_type,
                'pre_uploaded': False  # Mark as WebSocket-processed
            }
            
            print(f"[WORKER] ✅ After storing: processed_images has {len(processed_images_dict)} images")
            print(f"[WORKER] ✅ Stored image {image_id} in processed_images: {output_filename} ({len(output_bytes)} bytes)")
            print(f"[WORKER] 🔍 Current keys in processed_images: {list(processed_images_dict.keys())}")
            
            logger.info(f"[WORKER] ✅ Stored image {image_id} in processed_images (total stored: {len(processed_images_dict)})")
            
            # Verify this image is different from previously stored images in this batch
            for stored_id, stored_data in processed_images_dict.items():
                if stored_id.startswith(f"img_{batch_id}_") and stored_id != image_id:
                    stored_hash = hashlib.md5(stored_data['data'][:1024]).hexdigest()
                    if stored_hash == output_hash:
                        logger.warning(f"[WORKER] ⚠️ WARNING: Image {image_id} has same hash as {stored_id}! Possible duplicate processing.")
            
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
# async def process_batch_async(
#     batch_id: int,
#     image_data_list: List[bytes],
#     background_color: str,
#     file_type: str,
#     watermark: str,
#     filenames: List[str],
#     result_callback: Callable,
#     gpu_id: Optional[int] = None
# ):
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
                import hashlib
                input_hash = hashlib.md5(image_bytes[:1024]).hexdigest()
                
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
    # print(f"[WORKER] Batch {batch_id} completed with {len(results)} results")
    batch_elapsed = time.time() - batch_start
    logger.info(f"[WORKER] Batch {batch_id} completed in {batch_elapsed:.2f}s")
    
    return results