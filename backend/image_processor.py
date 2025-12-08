"""
Image Processor - GPU-based image processing using withoutbg library.
Handles background removal, color application, watermarking, and format conversion.
"""
from PIL import Image, ImageDraw, ImageFont
import io
import torch
import numpy as np
from gpu_manager import get_instance, NUM_GPUS, reset_gpu
import time

def optimize_image_size(image, max_dimension=1024):
    """
    Resize image if it's too large to speed up processing.
    
    Args:
        image: PIL Image
        max_dimension: Maximum width or height
    
    Returns:
        Resized PIL Image
    """
    width, height = image.size
    if width <= max_dimension and height <= max_dimension:
        return image
    
    # Calculate new dimensions maintaining aspect ratio
    if width > height:
        new_width = max_dimension
        new_height = int(height * (max_dimension / width))
    else:
        new_height = max_dimension
        new_width = int(width * (max_dimension / height))
    
    return image.resize((new_width, new_height), Image.Resampling.LANCZOS)

def add_checkerboard_background(img_with_alpha):
    """
    Add checkerboard pattern to transparent background for visualization.
    
    Args:
        img_with_alpha: PIL Image in RGBA mode
    
    Returns:
        PIL Image with checkerboard background
    """
    # Ensure RGBA
    img = img_with_alpha.convert("RGBA")
    w, h = img.size

    # Create checkerboard
    checker = make_checkerboard(w, h)

    # Use alpha channel as mask
    checker.paste(img, (0, 0), mask=img)
    return checker

def make_checkerboard(w, h, tile=40):
    """
    Create a checkerboard pattern image.
    
    Args:
        w: Width
        h: Height
        tile: Tile size
    
    Returns:
        PIL Image in RGBA mode
    """
    c1 = np.array([200, 200, 200, 255], dtype=np.uint8)
    c2 = np.array([255, 255, 255, 255], dtype=np.uint8)

    board = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            color = c1 if ((x//tile + y//tile) % 2 == 0) else c2
            board[y:y+tile, x:x+tile] = color

    return Image.fromarray(board, 'RGBA')

def add_pedals_watermark(image):
    """
    Add PEDALS to METAL.com watermark to the bottom right corner of the image.
    Includes three outlined circles (like pedal knobs) and "PEDALS to METAL.com" text.
    
    Args:
        image: PIL Image
    
    Returns:
        PIL Image with watermark
    """
    # Ensure image is in RGB mode for drawing
    if image.mode == "RGBA":
        # Create a white background for watermark
        watermark_bg = Image.new("RGB", image.size, (255, 255, 255))
        watermark_bg.paste(image, mask=image.split()[3])
        image = watermark_bg
    elif image.mode != "RGB":
        image = image.convert("RGB")
    
    # Create a copy to draw on
    img_with_watermark = image.copy()
    
    # Calculate watermark size based on image dimensions
    img_width, img_height = image.size
    base_font_size = max(14, int(img_width * 0.025))  # 2.5% of image width, minimum 14px
    small_font_size = max(10, int(base_font_size * 0.7))  # Smaller font for .com
    
    # Try to load fonts, fallback to default if not available
    try:
        main_font = ImageFont.truetype("arial.ttf", base_font_size)
        small_font = ImageFont.truetype("arial.ttf", small_font_size)
    except:
        try:
            main_font = ImageFont.truetype("arialbd.ttf", base_font_size)
            small_font = ImageFont.truetype("arial.ttf", small_font_size)
        except:
            # Fallback to default font
            main_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
    
    # Create a temporary drawing context to measure text
    temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    
    # Text parts
    main_text = "PEDALS to METAL"
    small_text = ".com"
    
    # Calculate text bounding boxes
    main_bbox = temp_draw.textbbox((0, 0), main_text, font=main_font)
    main_text_width = main_bbox[2] - main_bbox[0]
    main_text_height = main_bbox[3] - main_bbox[1]
    
    small_bbox = temp_draw.textbbox((0, 0), small_text, font=small_font)
    small_text_width = small_bbox[2] - small_bbox[0]
    small_text_height = small_bbox[3] - small_bbox[1]
    
    # Calculate circle dimensions (three circles like pedal knobs)
    circle_radius = max(4, int(img_width * 0.008))  # 0.8% of image width, minimum 4px
    circle_spacing = circle_radius * 2.5  # Space between circles
    circles_width = (circle_radius * 2 * 3) + (circle_spacing * 2)  # Total width of three circles
    
    # Total watermark width (circles or text, whichever is wider)
    watermark_width = max(circles_width, main_text_width + small_text_width)
    watermark_height = (circle_radius * 2) + 8 + main_text_height  # Circles + spacing + text
    
    # Position: bottom right with padding
    padding = max(10, int(img_width * 0.02))  # 2% of image width, minimum 10px
    watermark_x = img_width - watermark_width - padding
    watermark_y = img_height - watermark_height - padding
    
    # Create a semi-transparent overlay using RGBA
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    # Draw semi-transparent background rectangle for better visibility
    bg_padding = 8
    bg_rect = [
        watermark_x - bg_padding,
        watermark_y - bg_padding,
        watermark_x + watermark_width + bg_padding,
        watermark_y + watermark_height + bg_padding
    ]
    overlay_draw.rectangle(bg_rect, fill=(0, 0, 0, 150))  # Semi-transparent black background
    
    # Composite the overlay onto the image
    img_rgba = img_with_watermark.convert("RGBA")
    img_with_watermark = Image.alpha_composite(img_rgba, overlay).convert("RGB")
    
    # Draw on the composited image
    draw = ImageDraw.Draw(img_with_watermark)
    
    # Draw three outlined circles (like pedal knobs) at the top
    circle_y = watermark_y
    circle_start_x = watermark_x + (watermark_width - circles_width) / 2 + circle_radius
    
    for i in range(3):
        circle_x = circle_start_x + (i * (circle_radius * 2 + circle_spacing))
        # Draw circle outline (white)
        draw.ellipse(
            [
                circle_x - circle_radius,
                circle_y - circle_radius,
                circle_x + circle_radius,
                circle_y + circle_radius
            ],
            outline=(255, 255, 255),
            width=1
        )
    
    # Draw main text "PEDALS to METAL"
    text_y = watermark_y + (circle_radius * 2) + 8
    text_x = watermark_x + (watermark_width - main_text_width - small_text_width) / 2
    draw.text((text_x, text_y), main_text, fill=(255, 255, 255), font=main_font)
    
    # Draw small ".com" text offset to the bottom right
    com_x = text_x + main_text_width + 2
    com_y = text_y + (main_text_height - small_text_height) + 2  # Slightly offset down
    draw.text((com_x, com_y), small_text, fill=(255, 255, 255), font=small_font)
    
    return img_with_watermark

def process_image_sync(image_data, bg_color, output_format, watermark_option, filename='processed_image', gpu_id=None):
    """
    Synchronous image processing function for GPU execution.
    Processes a single image: removes background, applies color, adds watermark.
    
    Args:
        image_data: Image bytes or PIL Image
        bg_color: Background color ("transparent", "white", or "black")
        output_format: Output format ("PNG" or "JPEG")
        watermark_option: Watermark option ("none" or "blog")
        filename: Original filename
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        Tuple of (processed_image_bytes, mime_type, processed_filename, output_format)
    
    Raises:
        RuntimeError: If GPU is not available
    """
    if NUM_GPUS == 0:
        raise RuntimeError("No GPUs available - GPU is required for image processing")
    
    try:
        # Load image as PIL Image
        if isinstance(image_data, bytes):
            input_image = Image.open(io.BytesIO(image_data))
        elif isinstance(image_data, Image.Image):
            input_image = image_data
        else:
            raise ValueError(f"Unsupported image_data type: {type(image_data)}")
        
        # Optimize image size for faster processing
        input_image = optimize_image_size(input_image, max_dimension=1024)
        
        # Get GPU instance (round-robin if gpu_id is None)
        remover = get_instance(gpu_id)
        
        # Process image on GPU using withoutbg
        # The correct method is remove_background
        processed_image = remover.remove_background(input_image)
        
        # Ensure the result is in RGBA mode
        if processed_image.mode != 'RGBA':
            processed_image = processed_image.convert('RGBA')
        
        # Apply background color
        if bg_color == "transparent":
            # Create checkerboard pattern for transparent background
            if processed_image.mode == "RGBA":
                processed_image = add_checkerboard_background(processed_image)
            elif processed_image.mode != "RGB":
                processed_image = processed_image.convert("RGB")
        else:
            # Convert to RGB with specified background color
            if processed_image.mode == "RGBA":
                if bg_color == "white":
                    bg_rgb = (255, 255, 255)
                else:  # black
                    bg_rgb = (0, 0, 0)
                
                background = Image.new("RGB", processed_image.size, bg_rgb)
                background.paste(processed_image, mask=processed_image.split()[3])  # Use alpha channel as mask
                processed_image = background
            elif processed_image.mode != "RGB":
                processed_image = processed_image.convert("RGB")
        
        # Determine output format
        output_format = "PNG" if output_format.upper() == "PNG" else "JPEG"
        mime_type = "image/png" if output_format == "PNG" else "image/jpeg"
        
        # JPEG doesn't support transparency, so convert to RGB if needed
        if output_format == "JPEG" and processed_image.mode == "RGBA":
            # If transparent was requested but JPEG format, use white background
            if bg_color == "transparent":
                # For JPEG, we must use a solid background (white)
                rgb_image = Image.new("RGB", processed_image.size, (255, 255, 255))
                rgb_image.paste(processed_image, mask=processed_image.split()[3])
                processed_image = rgb_image
            else:
                # Use white background for JPEG
                rgb_image = Image.new("RGB", processed_image.size, (255, 255, 255))
                rgb_image.paste(processed_image, mask=processed_image.split()[3])
                processed_image = rgb_image
        
        # Add watermark if requested
        if watermark_option == "blog":
            processed_image = add_pedals_watermark(processed_image)
        
        # Convert processed image to bytes
        img_byte_arr = io.BytesIO()
        
        # Use lower quality for JPEG to reduce size and processing time
        quality = 80 if output_format == "JPEG" else 90
        processed_image.save(img_byte_arr, format=output_format, quality=quality, optimize=True)
        img_byte_arr.seek(0)
        processed_image_bytes = img_byte_arr.read()
        
        # Generate filename
        file_extension = "png" if output_format == "PNG" else "jpg"
        processed_filename = filename.rsplit('.', 1)[0] + f"-no-bg.{file_extension}"
        
        return processed_image_bytes, mime_type, processed_filename, output_format
        
    except Exception as e:
        gpu_info = f"GPU {gpu_id}" if gpu_id is not None else "GPU (auto-assigned)"
        error_msg = f"Error during background removal on {gpu_info}: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        raise Exception(error_msg)
    
    finally:
        # Cleanup GPU memory if gpu_id was explicitly provided
        if gpu_id is not None:
            try:
                with torch.cuda.device(gpu_id):
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
            except:
                pass

def process_batch_sync(image_data_list, bg_color, output_format, watermark_option, filenames=None, gpu_id=None):
    """
    Process a batch of images synchronously on GPU.
    
    Args:
        image_data_list: List of image bytes or PIL Images
        bg_color: Background color
        output_format: Output format
        watermark_option: Watermark option
        filenames: List of filenames (optional)
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        List of tuples: (processed_image_bytes, mime_type, processed_filename, output_format)
    """
    if NUM_GPUS == 0:
        raise RuntimeError("No GPUs available - GPU is required for image processing")
    
    if filenames is None:
        filenames = [f'image_{i}' for i in range(len(image_data_list))]
    
    results = []
    for idx, image_data in enumerate(image_data_list):
        try:
            filename = filenames[idx] if idx < len(filenames) else f'image_{idx}'
            result = process_image_sync(
                image_data, bg_color, output_format, watermark_option, filename, gpu_id
            )
            results.append(result)
        except Exception as e:
            print(f"Error processing image {idx} in batch: {str(e)}")
            # Return None for failed images
            results.append(None)
    
    return results
