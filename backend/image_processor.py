"""
Image processing with GPU model pooling and BATCH processing using transparent-background
"""
from PIL import Image
import io
from typing import Optional, Dict, List
import torch
import numpy as np

# Global model pool - one model per GPU, initialized once
_model_pool: Dict[int, any] = {}
_model_pool_initialized = False

def initialize_model_pool():
    """Initialize one transparent-background Remover model per GPU (called at startup)"""
    global _model_pool, _model_pool_initialized
    
    if _model_pool_initialized:
        return
    
    try:
        from transparent_background import Remover
        
        num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
        print(f"[MODEL_POOL] Initializing model pool with {num_gpus} GPU(s)")
        
        for gpu_id in range(num_gpus):
            print(f"[MODEL_POOL] Loading transparent-background model on GPU {gpu_id}...")
            
            # Set the CUDA device before creating the model
            torch.cuda.set_device(gpu_id)
            
            # Create model instance - transparent_background uses Remover class
            # mode='fast' is faster, mode='base' is higher quality
            model = Remover(device=f'cuda:{gpu_id}', mode='fast')  # Use 'fast' for speed!
            _model_pool[gpu_id] = model
            
            print(f"[MODEL_POOL] Model loaded on GPU {gpu_id}")
        
        _model_pool_initialized = True
        print(f"[MODEL_POOL] Model pool initialization complete: {len(_model_pool)} models ready")
        
    except Exception as e:
        print(f"[MODEL_POOL] Error initializing model pool: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def get_model_for_gpu(gpu_id: int):
    """Get the pre-loaded model for a specific GPU"""
    if not _model_pool_initialized:
        initialize_model_pool()
    
    if gpu_id not in _model_pool:
        raise ValueError(f"No model available for GPU {gpu_id}")
    
    return _model_pool[gpu_id]

def process_image_sync(
    image_data: bytes,
    background_color: str = "white",
    file_type: str = "JPEG",
    watermark: str = "none",
    filename: str = "image",
    gpu_id: Optional[int] = None
) -> tuple:
    """
    Process a single image using pre-loaded transparent-background model from pool.
    
    Args:
        image_data: Raw image bytes
        background_color: Background color ('white', 'black', 'transparent')
        file_type: Output format ('PNG' or 'JPEG')
        watermark: Watermark text (or 'none')
        filename: Original filename
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        tuple: (output_bytes, mime_type, output_filename, save_format)
    """
    try:
        # Determine GPU to use (round-robin if not specified)
        num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
        if gpu_id is None:
            # Simple round-robin based on a global counter
            import time
            gpu_id = int(time.time() * 1000) % num_gpus
        
        print(f"[PROCESSOR] Processing {filename} on GPU {gpu_id}")
        
        # Set CUDA device
        torch.cuda.set_device(gpu_id)
        
        # Load image
        input_image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary (transparent-background works best with RGB)
        if input_image.mode not in ('RGB', 'RGBA'):
            input_image = input_image.convert('RGB')
        
        # Get pre-loaded model from pool (NO NEW MODEL CREATION)
        remover = get_model_for_gpu(gpu_id)
        
        # Process image - transparent_background returns RGBA image
        # Single image processing
        processed_image = remover.process(input_image)
        
        # Apply background color and save
        output_bytes, mime_type, output_filename, save_format = _finalize_image(
            processed_image, background_color, file_type, watermark, filename
        )
        
        print(f"[PROCESSOR] Image {filename} processed successfully on GPU {gpu_id}")
        
        return (output_bytes, mime_type, output_filename, save_format)
        
    except Exception as e:
        print(f"[PROCESSOR] Error processing {filename}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def process_images_batch(
    image_data_list: List[bytes],
    filenames: List[str],
    background_color: str = "white",
    file_type: str = "JPEG",
    watermark: str = "none",
    gpu_id: Optional[int] = None
) -> List[tuple]:
    """
    Process multiple images in a batch using transparent-background.
    
    IMPORTANT: transparent-background doesn't have true batch inference at API level,
    but we can process images sequentially with the same model instance which is faster
    than creating new model instances.
    
    Args:
        image_data_list: List of raw image bytes
        filenames: List of original filenames
        background_color: Background color ('white', 'black', 'transparent')
        file_type: Output format ('PNG' or 'JPEG')
        watermark: Watermark text (or 'none')
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        List of tuples: [(output_bytes, mime_type, output_filename, save_format), ...]
    """
    try:
        # Determine GPU to use
        num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
        if gpu_id is None:
            import time
            gpu_id = int(time.time() * 1000) % num_gpus
        
        print(f"[PROCESSOR] Batch processing {len(image_data_list)} images on GPU {gpu_id}")
        
        # Set CUDA device
        torch.cuda.set_device(gpu_id)
        
        # Get pre-loaded model
        remover = get_model_for_gpu(gpu_id)
        
        results = []
        
        # Load all images first
        images = []
        valid_filenames = []
        for i, (image_data, filename) in enumerate(zip(image_data_list, filenames)):
            try:
                img = Image.open(io.BytesIO(image_data))
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                images.append(img)
                valid_filenames.append(filename)
            except Exception as e:
                print(f"[PROCESSOR] Error loading image {filename}: {e}")
                results.append(None)  # Mark as failed
        
        if not images:
            raise ValueError("No valid images to process")
        
        # Process images sequentially with same model instance
        # (transparent-background doesn't support true batch inference)
        processed_images = []
        for i, img in enumerate(images):
            try:
                # Process single image
                processed = remover.process(img)
                processed_images.append(processed)
                print(f"[PROCESSOR] Processed {i+1}/{len(images)}: {valid_filenames[i]}")
            except Exception as e:
                print(f"[PROCESSOR] Error processing {valid_filenames[i]}: {e}")
                processed_images.append(None)
        
        # Finalize all processed images
        for i, (processed, filename) in enumerate(zip(processed_images, valid_filenames)):
            if processed is not None:
                try:
                    result = _finalize_image(
                        processed, background_color, file_type, watermark, filename
                    )
                    results.append(result)
                except Exception as e:
                    print(f"[PROCESSOR] Error finalizing {filename}: {e}")
                    results.append(None)
            else:
                results.append(None)
        
        successful = len([r for r in results if r is not None])
        print(f"[PROCESSOR] Batch complete: {successful}/{len(image_data_list)} successful")
        
        return results
        
    except Exception as e:
        print(f"[PROCESSOR] Error in batch processing: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

def _finalize_image(
    processed_image: Image.Image,
    background_color: str,
    file_type: str,
    watermark: str,
    filename: str
) -> tuple:
    """
    Apply background color, watermark, and save image.
    
    Returns:
        tuple: (output_bytes, mime_type, output_filename, save_format)
    """
    # Apply background color
    if background_color.lower() == "transparent":
        final_image = processed_image
    else:
        # Create background with specified color
        if background_color.lower() == "white":
            bg_color = (255, 255, 255)
        elif background_color.lower() == "black":
            bg_color = (0, 0, 0)
        else:
            # Try to parse hex color or default to white
            try:
                if background_color.startswith('#'):
                    hex_color = background_color.lstrip('#')
                    bg_color = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
                else:
                    bg_color = (255, 255, 255)
            except:
                bg_color = (255, 255, 255)
        
        # Create background and composite
        background = Image.new("RGB", processed_image.size, bg_color)
        if processed_image.mode == "RGBA":
            background.paste(processed_image, mask=processed_image.split()[3])
        else:
            background.paste(processed_image)
        final_image = background
    
    # Add watermark if needed
    if watermark and watermark.lower() != "none":
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(final_image)
        
        # Simple watermark in corner
        text = watermark
        position = (10, final_image.height - 30)
        # Try to use default font
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()
        draw.text(position, text, fill=(128, 128, 128), font=font)
    
    # Save to bytes
    output_buffer = io.BytesIO()
    save_format = "PNG" if file_type.upper() == "PNG" else "JPEG"
    
    if save_format == "JPEG" and final_image.mode in ("RGBA", "LA", "P"):
        final_image = final_image.convert("RGB")
    
    final_image.save(output_buffer, format=save_format, quality=95)
    output_bytes = output_buffer.getvalue()
    
    # Determine output filename with correct extension
    base_filename = filename.rsplit('.', 1)[0] if '.' in filename else filename
    extension = "png" if save_format == "PNG" else "jpg"
    output_filename = f"{base_filename}_no_bg.{extension}"
    
    # Determine MIME type
    mime_type = f"image/{save_format.lower()}"
    
    return (output_bytes, mime_type, output_filename, save_format)