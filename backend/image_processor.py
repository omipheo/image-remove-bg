"""
Image processing with GPU model pooling and reuse
"""
from PIL import Image
import io
import base64
import uuid
from typing import Optional, Dict
import torch

# Global model pool - one model per GPU, initialized once
_model_pool: Dict[int, any] = {}
_model_pool_initialized = False

def initialize_model_pool():
    """Initialize one WithoutBG model per GPU (called at startup)"""
    global _model_pool, _model_pool_initialized
    
    if _model_pool_initialized:
        return
    
    try:
        from withoutbg import WithoutBG
        
        num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
        print(f"[MODEL_POOL] Initializing model pool with {num_gpus} GPU(s)")
        
        for gpu_id in range(num_gpus):
            print(f"[MODEL_POOL] Loading model on GPU {gpu_id}...")
            
            # Create model instance for this GPU
            model = WithoutBG(device=f"cuda:{gpu_id}")
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
) -> dict:
    """
    Process a single image using pre-loaded model from pool.
    
    Key changes:
    - Uses get_model_for_gpu() instead of creating new model
    - Much faster, no OOM errors
    """
    try:
        from withoutbg import WithoutBG
        import numpy as np
        
        # Determine GPU to use
        if gpu_id is None:
            num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
            gpu_id = 0  # Default to GPU 0
        
        print(f"[PROCESSOR] Processing {filename} on GPU {gpu_id}")
        
        # Load image
        input_image = Image.open(io.BytesIO(image_data))
        
        # Resize if too large (for speed)
        max_size = 1024
        if max(input_image.size) > max_size:
            ratio = max_size / max(input_image.size)
            new_size = tuple(int(dim * ratio) for dim in input_image.size)
            input_image = input_image.resize(new_size, Image.LANCZOS)
            print(f"[PROCESSOR] Resized image to {new_size}")
        
        # Get pre-loaded model from pool (NO NEW MODEL CREATION)
        remover = get_model_for_gpu(gpu_id)
        
        # Process image
        processed_image = remover.remove_background(input_image)
        
        # Apply background color
        if background_color.lower() == "transparent":
            final_image = processed_image
        else:
            # Create background
            background = Image.new("RGB", processed_image.size, background_color)
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
            draw.text(position, text, fill=(128, 128, 128))
        
        # Save to bytes
        output_buffer = io.BytesIO()
        save_format = "PNG" if file_type.upper() == "PNG" else "JPEG"
        
        if save_format == "JPEG" and final_image.mode in ("RGBA", "LA", "P"):
            final_image = final_image.convert("RGB")
        
        final_image.save(output_buffer, format=save_format, quality=95)
        output_bytes = output_buffer.getvalue()
        
        # Generate unique ID
        image_id = f"img_{uuid.uuid4().hex[:12]}"
        
        print(f"[PROCESSOR] Image {filename} processed successfully on GPU {gpu_id}")
        
        return {
            "success": True,
            "filename": filename,
            "imageId": image_id,
            "downloadUrl": f"/api/download/{image_id}",
            "format": save_format,
            "mimeType": f"image/{save_format.lower()}",
            "_image_id": image_id,
            "_image_data": output_bytes
        }
        
    except Exception as e:
        print(f"[PROCESSOR] Error processing {filename}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": False,
            "filename": filename,
            "error": str(e)
        }