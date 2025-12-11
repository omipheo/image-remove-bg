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
import zipfile
import tempfile
import os

logger = logging.getLogger(__name__)

# Import main module at module level to ensure we use the same instance
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


def create_zip_for_batch(batch_id: int, processed_images_dict: dict):
    """
    Create ZIP file containing all processed images for a batch.
    Store it inside processed_images dict.
    """
    zip_id = f"zip_{batch_id}_{int(time.time())}"
    tmp_dir = tempfile.gettempdir()
    zip_path = os.path.join(tmp_dir, f"{zip_id}.zip")

    print(f"[ZIP] Creating ZIP for batch {batch_id} -> {zip_path}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for image_id, data in processed_images_dict.items():
            if image_id.startswith(f"img_{batch_id}_"):
                filename = data.get("filename", f"{image_id}.jpg")
                z.writestr(filename, data["data"])
                print(f"[ZIP] Added {filename} to ZIP")

    processed_images_dict[zip_id] = {
        "filename": f"{zip_id}.zip",
        "file_path": zip_path,
        "mime_type": "application/zip",
        "pre_uploaded": False,
    }

    print(f"[ZIP] ZIP created: {zip_path}")
    return zip_id


def create_zip_for_all_images(processed_images_dict: dict, batch_ids: list = None):
    """
    Create ZIP file containing ALL processed images (from all batches).
    Store it inside processed_images dict.
    """
    zip_id = f"zip_all_{int(time.time())}"
    tmp_dir = tempfile.gettempdir()
    zip_path = os.path.join(tmp_dir, f"{zip_id}.zip")

    print(f"[ZIP] Creating ZIP for all images -> {zip_path}")

    image_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for image_id, data in processed_images_dict.items():
            # Skip existing ZIP files and only include image files
            if image_id.startswith("zip_"):
                continue
            
            # If batch_ids specified, only include images from those batches
            if batch_ids:
                image_batch_id = None
                # Extract batch ID from image_id (format: img_{batch_id}_{task_id}_{timestamp})
                parts = image_id.split("_")
                if len(parts) >= 2 and parts[0] == "img":
                    try:
                        image_batch_id = int(parts[1])
                    except ValueError:
                        pass
                
                if image_batch_id is None or image_batch_id not in batch_ids:
                    continue
            
            # Only include images (not ZIPs)
            if image_id.startswith("img_"):
                filename = data.get("filename", f"{image_id}.jpg")
                if "data" in data:
                    z.writestr(filename, data["data"])
                    image_count += 1
                    if image_count % 10 == 0:
                        print(f"[ZIP] Added {image_count} images to ZIP...")

    processed_images_dict[zip_id] = {
        "filename": f"{zip_id}.zip",
        "file_path": zip_path,
        "mime_type": "application/zip",
        "pre_uploaded": False,
    }

    print(f"[ZIP] ZIP created: {zip_path} with {image_count} images")
    return zip_id


# Global batch queue
_batch_queue = asyncio.Queue()
_batch_processor_started = False
_processing_semaphore = asyncio.Semaphore(max(1, NUM_GPUS * 8))


def get_processing_semaphore():
    return _processing_semaphore


def get_batch_queue():
    return _batch_queue


def start_batch_processor():
    """Initialize the batch processor (currently using model pool instead of separate processor)"""
    global _batch_processor_started
    if not _batch_processor_started:
        initialize_model_pool()
        _batch_processor_started = True
        print("[BATCH_PROCESSOR] Batch processor initialized with model pool")



async def process_batch_parallel(batch_images, batch_id, config, callback):
    """
    Process batch of images in parallel across GPUs - optimized for 4x RTX 3090.
    """
    logger.info(f"[WORKER] Starting batch {batch_id} with {len(batch_images)} images")

    async def process_single_image(task_id, img_data):
        try:
            pil_image = img_data['image']
            filename = img_data['filename']

            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            image_bytes = img_byte_arr.read()

            bg_color = config.get('backgroundColor', 'white')
            file_type = config.get('fileType', 'JPEG')
            watermark = config.get('watermark', 'none')

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
                None
            )

            output_bytes, mime_type, output_filename, save_format = result_tuple

            import hashlib
            output_hash = hashlib.md5(output_bytes[:1024]).hexdigest()

            image_id = f"img_{batch_id}_{task_id}_{int(time.time())}"

            processed_images_dict = get_processed_images()
            main_module = get_main_module()

            print(f"[WORKER] 🔍 Before storing: processed_images has {len(processed_images_dict)} images")
            processed_images_dict[image_id] = {
                'data': output_bytes,
                'filename': output_filename,
                'format': save_format,
                'mime_type': mime_type,
                'pre_uploaded': False
            }
            print(f"[WORKER] 🔍 After storing: processed_images has {len(processed_images_dict)} images")

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

            if callback:
                await callback(result)

            return result

        except Exception as e:
            logger.error(f"[WORKER] Error processing task {task_id}: {e}", exc_info=True)
            error_result = {
                'batch_id': batch_id,
                'task_id': task_id,
                'filename': img_data.get('filename', 'unknown'),
                'success': False,
                'error': str(e)
            }
            if callback:
                try:
                    await callback(error_result)
                except Exception:
                    pass
            return error_result

    tasks = [
        process_single_image(task_id, img_data)
        for task_id, img_data in batch_images.items()
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
