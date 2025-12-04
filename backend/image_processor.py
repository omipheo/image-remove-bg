"""Image processing functions: background removal, watermarking, optimization"""
import io
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from gpu_manager import get_instance, NUM_GPUS
import torch


def optimize_image_size(image, max_dimension=2048):
    """
    Resize image if it's too large to speed up processing.
    With 96GB VRAM, we can process larger images without resizing.
    Increased limit for better quality while maintaining speed.
    """
    width, height = image.size
    # With 96GB VRAM, we can handle larger images (2048px is good balance)
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


def make_checkerboard(w, h, tile=40):
    """Create a checkerboard pattern for transparent backgrounds"""
    c1 = np.array([200, 200, 200, 255], dtype=np.uint8)
    c2 = np.array([255, 255, 255, 255], dtype=np.uint8)

    board = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            color = c1 if ((x//tile + y//tile) % 2 == 0) else c2
            board[y:y+tile, x:x+tile] = color

    return Image.fromarray(board, 'RGBA')


def add_checkerboard_background(img_with_alpha):
    """Add checkerboard background to transparent image"""
    # Ensure RGBA
    img = img_with_alpha.convert("RGBA")
    w, h = img.size

    # Create checkerboard
    checker = make_checkerboard(w, h)

    # Use alpha channel as mask
    checker.paste(img, (0, 0), mask=img)
    return checker


def add_pedals_watermark(image):
    """
    Add PEDALS to METAL.com watermark to the bottom right corner of the image.
    Includes three outlined circles (like pedal knobs) and "PEDALS to METAL.com" text.
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
    """Synchronous image processing function for thread pool execution"""
    from gpu_manager import reset_gpu
    
    # Load image as PIL Image
    input_image = Image.open(io.BytesIO(image_data))
    
    # Optimize image size - reduce to prevent GPU memory exhaustion
    # Balance between quality and memory usage (1024px uses less memory than 2048px)
    input_image = optimize_image_size(input_image, max_dimension=1024)  # Reduced to prevent CUDA OOM
    
    processed_image = None
    # Set GPU device context explicitly to prevent cross-device memory issues
    if gpu_id is not None and NUM_GPUS > 0:
        torch.cuda.set_device(gpu_id)
    
    max_retries = 2  # Retry once after GPU reset
    for attempt in range(max_retries):
        try:
            withoutbg_instance = get_instance(gpu_id=gpu_id)
            # withoutbg remove_background() accepts PIL Image and returns PIL Image
            # Instances can be reused for multiple images and support batch processing
            processed_image = withoutbg_instance.remove_background(input_image)
            
            # withoutbg returns PIL.Image directly
            if not isinstance(processed_image, Image.Image):
                raise ValueError(f"Expected PIL.Image, got {type(processed_image)}")
            
            # Synchronize GPU operations to ensure completion before clearing cache
            if gpu_id is not None and NUM_GPUS > 0:
                try:
                    with torch.cuda.device(gpu_id):
                        torch.cuda.synchronize()  # Wait for all GPU operations to complete
                        torch.cuda.empty_cache()
                except:
                    pass  # Ignore errors in cleanup
            
            # Success - break out of retry loop
            break
            
        except RuntimeError as e:
            error_str = str(e)
            # Check if it's a CUDA illegal memory access error
            if "illegal memory access" in error_str.lower() or "cudaErrorIllegalAddress" in error_str:
                if attempt < max_retries - 1:
                    print(f"CUDA illegal memory access detected on GPU {gpu_id}, resetting GPU and retrying...")
                    # Reset GPU and retry
                    reset_gpu(gpu_id)
                    # Small delay before retry
                    import time
                    time.sleep(0.5)
                    continue
                else:
                    # Last attempt failed
                    raise Exception(f"CUDA illegal memory access after GPU reset: {error_str}")
            else:
                # Other RuntimeError - don't retry
                raise
        except Exception as e:
            # Clear GPU cache on error too
            if gpu_id is not None and NUM_GPUS > 0:
                try:
                    with torch.cuda.device(gpu_id):
                        torch.cuda.synchronize()
                        torch.cuda.empty_cache()
                except:
                    pass
            import traceback
            error_msg = f"Error during background removal: {str(e)}"
            print(error_msg)
            print(traceback.format_exc())
            raise Exception(error_msg)
    
    # Ensure the result is in RGBA mode
    if processed_image.mode != 'RGBA':
        processed_image = processed_image.convert('RGBA')
    
    # Apply background color
    if bg_color == "transparent":
        # Create checkerboard pattern for transparent background
        if processed_image.mode == "RGBA":
            # Create checkerboard pattern
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
    
    # Convert processed image to bytes
    img_byte_arr = io.BytesIO()
    
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
    
    # Use lower quality for JPEG to reduce size and processing time
    quality = 85 if output_format == "JPEG" else 95
    processed_image.save(img_byte_arr, format=output_format, quality=quality, optimize=True)
    img_byte_arr.seek(0)
    processed_image_bytes = img_byte_arr.read()
    
    # Generate filename
    file_extension = "png" if output_format == "PNG" else "jpg"
    processed_filename = filename.rsplit('.', 1)[0] + f"-no-bg.{file_extension}"
    
    return processed_image_bytes, mime_type, processed_filename, output_format


def process_batch_sync(image_data_list, bg_color, output_format, watermark_option, filenames=None, gpu_id=None):
    """
    Process multiple images in batch using withoutbg's batch processing.
    This is more efficient than processing images one by one.
    
    Args:
        image_data_list: List of image data (bytes) to process
        bg_color: Background color ("transparent", "white", or "black")
        output_format: Output format ("PNG" or "JPEG")
        watermark_option: Watermark option ("none" or "blog")
        filenames: Optional list of filenames (defaults to "processed_image_N")
        gpu_id: GPU ID to use (None for round-robin)
    
    Returns:
        List of tuples: (processed_image_bytes, mime_type, processed_filename, output_format)
    """
    from gpu_manager import get_instance, reset_gpu
    
    if filenames is None:
        filenames = [f'processed_image_{i}' for i in range(len(image_data_list))]
    
    # Get withoutbg instance once for the batch
    withoutbg_instance = get_instance(gpu_id=gpu_id)
    
    # Set GPU device context
    if gpu_id is not None and NUM_GPUS > 0:
        torch.cuda.set_device(gpu_id)
    
    results = []
    
    try:
        # Prepare input images for batch processing
        input_images = []
        for image_data in image_data_list:
            input_image = Image.open(io.BytesIO(image_data))
            input_image = optimize_image_size(input_image, max_dimension=1024)
            input_images.append(input_image)
        
        # Process all images in batch using withoutbg's batch processing
        print(f"Processing batch of {len(input_images)} images using withoutbg batch processing...")
        processed_images = withoutbg_instance.remove_background_batch(input_images)
        
        # Process each result
        for idx, (processed_image, filename) in enumerate(zip(processed_images, filenames)):
            try:
                
                # Ensure RGBA mode
                if processed_image.mode != 'RGBA':
                    processed_image = processed_image.convert('RGBA')
                
                # Apply background color
                if bg_color == "transparent":
                    if processed_image.mode == "RGBA":
                        processed_image = add_checkerboard_background(processed_image)
                    elif processed_image.mode != "RGB":
                        processed_image = processed_image.convert("RGB")
                else:
                    if processed_image.mode == "RGBA":
                        if bg_color == "white":
                            bg_rgb = (255, 255, 255)
                        else:  # black
                            bg_rgb = (0, 0, 0)
                        background = Image.new("RGB", processed_image.size, bg_rgb)
                        background.paste(processed_image, mask=processed_image.split()[3])
                        processed_image = background
                    elif processed_image.mode != "RGB":
                        processed_image = processed_image.convert("RGB")
                
                # Determine output format
                output_format_final = "PNG" if output_format.upper() == "PNG" else "JPEG"
                mime_type = "image/png" if output_format_final == "PNG" else "image/jpeg"
                
                # Convert to bytes
                img_byte_arr = io.BytesIO()
                
                # JPEG doesn't support transparency
                if output_format_final == "JPEG" and processed_image.mode == "RGBA":
                    if bg_color == "transparent":
                        rgb_image = Image.new("RGB", processed_image.size, (255, 255, 255))
                        rgb_image.paste(processed_image, mask=processed_image.split()[3])
                        processed_image = rgb_image
                    else:
                        rgb_image = Image.new("RGB", processed_image.size, (255, 255, 255))
                        rgb_image.paste(processed_image, mask=processed_image.split()[3])
                        processed_image = rgb_image
                
                # Add watermark if requested
                if watermark_option == "blog":
                    processed_image = add_pedals_watermark(processed_image)
                
                # Save
                quality = 85 if output_format_final == "JPEG" else 95
                processed_image.save(img_byte_arr, format=output_format_final, quality=quality, optimize=True)
                img_byte_arr.seek(0)
                processed_image_bytes = img_byte_arr.read()
                
                # Generate filename
                file_extension = "png" if output_format_final == "PNG" else "jpg"
                processed_filename = filename.rsplit('.', 1)[0] + f"-no-bg.{file_extension}"
                
                results.append((processed_image_bytes, mime_type, processed_filename, output_format_final))
                
            except Exception as e:
                import traceback
                error_msg = f"Error processing image {idx + 1} ({filename}): {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                # Add None to results to maintain index alignment
                results.append(None)
        
        # Clear GPU cache after batch
        if gpu_id is not None and NUM_GPUS > 0:
            try:
                with torch.cuda.device(gpu_id):
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
            except:
                pass
        
        return results
        
    except Exception as e:
        # Clear GPU cache on error
        if gpu_id is not None and NUM_GPUS > 0:
            try:
                with torch.cuda.device(gpu_id):
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
            except:
                pass
        import traceback
        error_msg = f"Error during batch processing: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        raise Exception(error_msg)

