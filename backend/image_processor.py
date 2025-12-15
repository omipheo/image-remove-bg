"""
Image processing with GPU model pooling and BATCH processing using transparent-background
"""
from PIL import Image, ImageDraw, ImageFont
import io
from typing import Optional, Dict, List
import torch
import numpy as np
import math
import os

# Global model pool - one model per GPU, initialized once
_model_pool: Dict[int, any] = {}
_model_pool_initialized = False

def initialize_model_pool():
    """Initialize one transparent-background Remover model per GPU (called at startup)
    
    In multi-GPU mode (CUDA_VISIBLE_DEVICES set), only initializes the visible GPU.
    In single-process mode, initializes all available GPUs.
    """
    global _model_pool, _model_pool_initialized
    
    if _model_pool_initialized:
        return
    
    try:
        from transparent_background import Remover
        
        # Check if we're in single-GPU-per-process mode
        gpu_id_env = os.getenv("GPU_ID")
        cuda_visible = os.getenv("CUDA_VISIBLE_DEVICES")
        
        if gpu_id_env is not None or cuda_visible is not None:
            # Single-GPU-per-process mode: only initialize GPU 0 (which is the pinned GPU)
            num_gpus = 1
            print(f"[MODEL_POOL] Single-GPU-per-process mode detected (GPU_ID={gpu_id_env}, CUDA_VISIBLE_DEVICES={cuda_visible})")
            print(f"[MODEL_POOL] Initializing model on GPU 0 (pinned GPU)...")
            
            torch.cuda.set_device(0)
            model = Remover(device='cuda:0', mode='fast', jit=False)
            _model_pool[0] = model
            
            print(f"[MODEL_POOL] Model loaded on pinned GPU (visible as GPU 0)")
        else:
            # Multi-GPU mode: initialize all GPUs
            num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
            print(f"[MODEL_POOL] Multi-GPU mode: Initializing model pool with {num_gpus} GPU(s)")
            
            for gpu_id in range(num_gpus):
                print(f"[MODEL_POOL] Loading transparent-background model on GPU {gpu_id}...")
                
                # Set the CUDA device before creating the model
                torch.cuda.set_device(gpu_id)
                
                # Use 'fast' mode for speed - optimized for RTX 3090
                model = Remover(device=f'cuda:{gpu_id}', mode='fast', jit=False)
                _model_pool[gpu_id] = model
                
                print(f"[MODEL_POOL] Model loaded on GPU {gpu_id}")
        
        _model_pool_initialized = True
        print(f"[MODEL_POOL] Model pool initialization complete: {len(_model_pool)} model(s) ready")
        
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
        # Determine GPU to use
        # In single-GPU-per-process mode, always use GPU 0 (the pinned GPU)
        gpu_id_env = os.getenv("GPU_ID")
        cuda_visible = os.getenv("CUDA_VISIBLE_DEVICES")
        
        if gpu_id_env is not None or cuda_visible is not None:
            # Single-GPU-per-process mode: always use GPU 0
            gpu_id = 0
        else:
            # Multi-GPU mode: use round-robin if not specified
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
        
        # Optional FP16 (disabled by default to preserve output quality)
        use_fp16 = os.getenv("USE_FP16", "false").lower() == "true"
        autocast_dtype = torch.float16 if use_fp16 else None
        with torch.cuda.amp.autocast(enabled=use_fp16, dtype=autocast_dtype):
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
    OPTIMIZED for 4x RTX 3090 setup.
    
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
        use_fp16 = os.getenv("USE_FP16", "false").lower() == "true"
        autocast_dtype = torch.float16 if use_fp16 else None
        for i, img in enumerate(images):
            try:
                # Process single image with optional FP16 autocast
                with torch.cuda.amp.autocast(enabled=use_fp16, dtype=autocast_dtype):
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

def _add_watermark_design(image: Image.Image, background_color: str, watermark: str) -> Image.Image:
    """
    Add watermark design matching the frontend addWatermark function.
    Creates "PEDALS to METAL.com" watermark with circles, rounded rectangle, and text.
    
    Args:
        image: PIL Image to add watermark to
        background_color: Background color for determining watermark color
        watermark: Watermark text (if "blog", uses "PEDALS to METAL.com" design)
    
    Returns:
        PIL Image with watermark added
    """
    if watermark.lower() == "blog":
        # Use the full "PEDALS to METAL.com" design
        return _add_pedals_to_metal_watermark(image, background_color)
    else:
        # Simple text watermark for other cases
        return _add_simple_text_watermark(image, background_color, watermark)


def _add_pedals_to_metal_watermark(image: Image.Image, background_color: str) -> Image.Image:
    """
    Add "PEDALS to METAL.com" watermark design matching frontend implementation.
    """
    draw = ImageDraw.Draw(image)
    
    # Calculate sizes based on image dimensions (matching frontend)
    base_font_size = max(14, int(image.width * 0.025))  # 2.5% of width, min 14px
    small_font_size = max(10, int(base_font_size * 0.7))  # Smaller font for .com
    
    # Determine watermark color based on background
    bg_color = background_color.lower()
    watermark_color = (0, 0, 0) if (bg_color == 'white' or bg_color == 'transparent') else (255, 255, 255)
    
    # Load fonts
    bold_font = _load_font(base_font_size, bold=True)
    italic_font = _load_font(int(base_font_size * 0.6), italic=True)
    small_italic_font = _load_font(small_font_size, italic=True)
    
    # Text parts
    pedals_text = 'PEDALS'
    to_text = 'to'
    metal_text = 'METAL'
    com_text = '.com'
    
    # Measure text widths
    pedals_bbox = draw.textbbox((0, 0), pedals_text, font=bold_font)
    pedals_width = pedals_bbox[2] - pedals_bbox[0]
    
    to_bbox = draw.textbbox((0, 0), to_text, font=italic_font)
    to_width = to_bbox[2] - to_bbox[0]
    
    metal_bbox = draw.textbbox((0, 0), metal_text, font=bold_font)
    metal_width = metal_bbox[2] - metal_bbox[0]
    
    com_bbox = draw.textbbox((0, 0), com_text, font=small_italic_font)
    com_width = com_bbox[2] - com_bbox[0]
    
    main_text_width = pedals_width + 5 + to_width + 5 + metal_width + 5 + com_width
    main_text_height = base_font_size
    
    # Calculate circle dimensions (three circles like pedal knobs)
    circle_radius = max(6, int(image.width * 0.01))  # 1% of width, min 6px
    circle_spacing = int(circle_radius * 2.2)
    circles_width = (circle_radius * 2 * 3) + (circle_spacing * 2)
    
    # Rounded rectangle around circles
    rect_padding = int(circle_radius * 0.8)
    rect_width = circles_width + (rect_padding * 2)
    rect_height = (circle_radius * 2) + (rect_padding * 2)
    rect_radius = int(circle_radius * 0.5)
    
    # Total watermark dimensions
    watermark_width = max(rect_width, main_text_width)
    watermark_height = rect_height + 10 + main_text_height
    
    # Position: bottom right with padding
    padding = max(10, int(image.width * 0.02))  # 2% of width, min 10px
    watermark_x = image.width - watermark_width - padding
    watermark_y = image.height - watermark_height - padding
    
    # Draw rounded rectangle around circles
    rect_x = watermark_x + (watermark_width - rect_width) // 2
    rect_y = watermark_y
    
    # Draw rounded rectangle (simplified - PIL doesn't have roundRect)
    draw.rectangle(
        [(rect_x, rect_y), (rect_x + rect_width, rect_y + rect_height)],
        outline=watermark_color,
        width=2
    )
    
    # Draw three circles with gear-like appearance
    circle_y = rect_y + rect_padding + circle_radius
    circle_start_x = rect_x + rect_padding + circle_radius
    
    for i in range(3):
        circle_x = circle_start_x + (i * (circle_radius * 2 + circle_spacing))
        
        # Draw circle with wavy edge (gear-like)
        # Create a path with multiple points for wavy edge
        circle_points = []
        segments = 16
        for j in range(segments + 1):
            angle = (j / segments) * math.pi * 2
            wave_offset = math.sin(angle * 4) * (circle_radius * 0.1)
            r = circle_radius + wave_offset
            x = circle_x + math.cos(angle) * r
            y = circle_y + math.sin(angle) * r
            circle_points.append((x, y))
        
        # Draw circle outline
        if len(circle_points) > 1:
            draw.polygon(circle_points, outline=watermark_color, width=1)
        
        # Draw inner knob: central dot
        inner_radius = int(circle_radius * 0.15)
        draw.ellipse(
            [(circle_x - inner_radius, circle_y - inner_radius),
             (circle_x + inner_radius, circle_y + inner_radius)],
            fill=watermark_color
        )
        
        # Draw inner knob: pointer line (12 o'clock position)
        pointer_length = int(circle_radius * 0.6)
        pointer_end_x = circle_x
        pointer_end_y = circle_y - pointer_length
        draw.line(
            [(circle_x, circle_y), (pointer_end_x, pointer_end_y)],
            fill=watermark_color,
            width=1
        )
    
    # Draw text "PEDALS to METAL.com"
    text_y = rect_y + rect_height + 10
    text_x = watermark_x + (watermark_width - main_text_width) // 2
    
    # Draw "PEDALS"
    pedals_x = text_x
    draw.text((pedals_x, text_y), pedals_text, fill=watermark_color, font=bold_font)
    
    # Draw "to"
    to_x = pedals_x + pedals_width + 5
    draw.text((to_x, int(text_y + base_font_size * 0.2)), to_text, fill=watermark_color, font=italic_font)
    
    # Draw "METAL"
    metal_x = to_x + to_width + 5
    draw.text((metal_x, text_y), metal_text, fill=watermark_color, font=bold_font)
    
    # Draw ".com" with cloud-like outline
    com_x = metal_x + metal_width + 5
    com_y = int(text_y + (base_font_size - small_font_size) + 2)
    
    # Draw cloud-like outline around ".com"
    cloud_padding = 3
    cloud_width = com_width + (cloud_padding * 2)
    cloud_height = small_font_size + (cloud_padding * 2)
    cloud_x = com_x - cloud_padding
    cloud_y = com_y - cloud_padding
    
    # Create irregular cloud-like shape
    cloud_points = []
    cloud_points_count = 8
    center_x = cloud_x + cloud_width // 2
    center_y = cloud_y + cloud_height // 2
    base_radius = min(cloud_width, cloud_height) // 2
    
    for i in range(cloud_points_count + 1):
        angle = (i / cloud_points_count) * math.pi * 2
        radius_variation = 1 + math.sin(angle * 3) * 0.3
        r = base_radius * radius_variation
        x = center_x + math.cos(angle) * r
        y = center_y + math.sin(angle) * r
        cloud_points.append((x, y))
    
    if len(cloud_points) > 2:
        draw.polygon(cloud_points, outline=watermark_color, width=1)
    
    # Draw ".com" text
    draw.text((com_x, com_y), com_text, fill=watermark_color, font=small_italic_font)
    
    return image


def _add_simple_text_watermark(image: Image.Image, background_color: str, watermark: str) -> Image.Image:
    """
    Add simple text watermark (for non-blog watermarks).
    """
    draw = ImageDraw.Draw(image)
    
    # Get watermark text
    text = watermark.upper() if watermark.lower() == "blog" else watermark
    
    # Calculate font size based on image size
    base_font_size = max(20, int(image.width * 0.025))
    font = _load_font(base_font_size, bold=True)
    
    # Determine text color based on background
    if background_color.lower() in ("white", "transparent"):
        text_color = (0, 0, 0)  # Black
        outline_color = (255, 255, 255)  # White outline
    else:
        text_color = (255, 255, 255)  # White
        outline_color = (0, 0, 0)  # Black outline
    
    # Calculate text position
    padding = max(15, int(image.width * 0.02))
    
    # Get text bounding box
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except:
        text_width = len(text) * base_font_size * 0.6
        text_height = base_font_size
    
    # Position: bottom right
    x = image.width - text_width - padding
    y = image.height - text_height - padding
    
    # Draw text outline for visibility
    outline_width = max(1, int(base_font_size * 0.05))
    for adj in range(-outline_width, outline_width + 1):
        for adj2 in range(-outline_width, outline_width + 1):
            if adj != 0 or adj2 != 0:
                draw.text((x + adj, y + adj2), text, fill=outline_color, font=font)
    
    # Draw main text
    draw.text((x, y), text, fill=text_color, font=font)
    
    return image


def _load_font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    """
    Load font with fallback options.
    """
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "arial.ttf",
        "Arial.ttf",
    ]
    
    # Try bold italic first if both requested
    if bold and italic:
        for path in font_paths:
            if "Bold" in path and ("Oblique" in path or "Italic" in path):
                try:
                    if os.path.exists(path):
                        return ImageFont.truetype(path, size)
                except:
                    continue
    
    # Try bold
    if bold:
        for path in font_paths:
            if "Bold" in path and "Oblique" not in path and "Italic" not in path:
                try:
                    if os.path.exists(path):
                        return ImageFont.truetype(path, size)
                except:
                    continue
    
    # Try italic
    if italic:
        for path in font_paths:
            if ("Italic" in path or "Oblique" in path) and "Bold" not in path:
                try:
                    if os.path.exists(path):
                        return ImageFont.truetype(path, size)
                except:
                    continue
    
    # Try any font
    for path in font_paths:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except:
            continue
    
    # Fallback to default
    return ImageFont.load_default()


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
        final_image = _add_watermark_design(final_image, background_color, watermark)
    
    # Save to bytes
    output_buffer = io.BytesIO()
    save_format = "PNG" if file_type.upper() == "PNG" else "JPEG"
    
    if save_format == "JPEG" and final_image.mode in ("RGBA", "LA", "P"):
        final_image = final_image.convert("RGB")
    
    # OPTIMIZATION: Reduce JPEG quality for faster processing
    quality = 85 if save_format == "JPEG" else 95
    final_image.save(output_buffer, format=save_format, quality=quality, optimize=True)
    output_bytes = output_buffer.getvalue()
    
    # Determine output filename with correct extension
    base_filename = filename.rsplit('.', 1)[0] if '.' in filename else filename
    extension = "png" if save_format == "PNG" else "jpg"
    output_filename = f"{base_filename}_no_bg.{extension}"
    
    # Determine MIME type
    mime_type = f"image/{save_format.lower()}"
    
    return (output_bytes, mime_type, output_filename, save_format)