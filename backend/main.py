from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from PIL import Image, ImageDraw, ImageFont
import io
from transparent_background import Remover
import uvicorn
import os
from dotenv import load_dotenv
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Image Background Removal API")

# Get CORS origins from environment variable or use defaults
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    cors_origins = cors_origins_env.split(",")
else:
    # Default origins including localhost (for SSH port forwarding) and HTTPS
    # Note: Vast.ai uses random public ports, so we include common port patterns
    cors_origins = [
        "http://localhost",
        "http://localhost:80",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:80",
        "https://localhost",
        "https://127.0.0.1",
        "http://161.184.141.187",
        "https://161.184.141.187",
        # Vast.ai mapped ports (update if ports change)
        "http://161.184.141.187:43752",
        "https://161.184.141.187:43930"
    ]

# Configure CORS to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store processed images temporarily (in production, use a proper storage solution)
processed_images = {}

# Initialize transparent-background remover (lazy load on first use)
_remover = None

# Thread pool for CPU-bound operations
_executor = ThreadPoolExecutor(max_workers=4)

def get_remover():
    """Lazy load the remover to avoid loading model on startup"""
    global _remover
    if _remover is None:
        try:
            print("Initializing transparent_background Remover...")
            _remover = Remover()
            print("Remover initialized successfully")
        except Exception as e:
            print(f"Error initializing Remover: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    return _remover

def optimize_image_size(image, max_dimension=2048):
    """Resize image if it's too large to speed up processing"""
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


def _process_image_sync(image_data, bg_color, output_format, watermark_option, filename='processed_image'):
    """Synchronous image processing function for thread pool execution"""
    # Load image as PIL Image
    input_image = Image.open(io.BytesIO(image_data))
    
    # Optimize image size for faster processing
    input_image = optimize_image_size(input_image, max_dimension=2048)
    
    try:
        remover = get_remover()
        # transparent-background expects PIL Image and returns PIL Image with RGBA
        processed_image = remover.process(input_image, type='rgba')
    except Exception as e:
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

async def process_single_image(file, bg_color, output_format, watermark_option):
    """
    Process a single image: remove background, apply color, and watermark.
    Returns processed image bytes, mime_type, and filename.
    Uses thread pool for CPU-bound operations.
    """
    # Read image file
    if hasattr(file, 'read'):
        # It's an UploadFile, read it asynchronously
        image_data = await file.read()
        filename = getattr(file, 'filename', 'processed_image') or 'processed_image'
    else:
        # It's already bytes
        image_data = file
        filename = 'processed_image'
    
    # Run CPU-bound processing in thread pool
    loop = asyncio.get_event_loop()
    processed_image_bytes, mime_type, processed_filename, output_format_final = await loop.run_in_executor(
        _executor,
        _process_image_sync,
        image_data,
        bg_color,
        output_format,
        watermark_option,
        filename
    )
    
    return processed_image_bytes, mime_type, processed_filename, output_format_final


@app.get("/")
async def root():
    return {"message": "Image Background Removal API", "status": "running"}


@app.post("/api/upload")
async def upload_image(request: Request):
    """
    Upload an image and remove its background.
    Returns the processed image as base64 or URL.
    
    Parameters:
    - backgroundColor: "transparent", "white", or "black"
    - fileType: "PNG" or "JPEG"
    """
    # breakpoint()
    try:
        # Parse form data manually to handle optional fields
        form_data = await request.form()
        
        # Get file from form data
        file = form_data.get("image")
        if not file:
            print("DEBUG: No file found in form_data")
            print(f"DEBUG: form_data keys: {list(form_data.keys())}")
            raise HTTPException(status_code=400, detail="Image file is required")
        
        # Check if it's an UploadFile instance (can be FastAPI's UploadFile or Starlette's)
        if not isinstance(file, (UploadFile, StarletteUploadFile)):
            # Check if it has the required attributes instead
            if not hasattr(file, 'read') or not hasattr(file, 'content_type'):
                raise HTTPException(status_code=400, detail="Invalid file type")
        
        # Get optional parameters with defaults
        backgroundColor = form_data.get("backgroundColor", "white")
        fileType = form_data.get("fileType", "JPEG")
        watermark = form_data.get("watermark", "none")
        
        # Normalize and validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "white"
        output_format = fileType.upper() if fileType else "JPEG"
        watermark_option = watermark.lower() if watermark else "none"
        
        # Validate file type
        if not hasattr(file, 'content_type') or not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Validate parameters
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(status_code=400, detail="backgroundColor must be 'transparent', 'white', or 'black'")
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(status_code=400, detail="fileType must be 'PNG' or 'JPEG'")
        
        if watermark_option not in ["none", "blog"]:
            raise HTTPException(status_code=400, detail="watermark must be 'none' or 'blog'")
        
        # Process the image using helper function
        processed_image_bytes, mime_type, processed_filename, output_format = await process_single_image(
            file, bg_color, output_format, watermark_option
        )
        
        # Convert to base64 for frontend
        import base64
        print("Encoding to base64...")
        image_base64 = base64.b64encode(processed_image_bytes).decode("utf-8")
        print(f"Base64 encoded size: {len(image_base64)} characters")
        image_url = f"data:{mime_type};base64,{image_base64}"
        print("Image processing completed, returning response")
        
        # Store the processed image (in production, use proper storage)
        image_id = f"img_{len(processed_images)}"
        processed_images[image_id] = {
            "data": processed_image_bytes,
            "filename": processed_filename,
            "format": output_format,
            "mime_type": mime_type
        }
        
        return {
            "imageUrl": image_url,
            "imageId": image_id,
            "message": "Background removed successfully"
        }
        
    except HTTPException as e:
        print(f"HTTPException: {e.detail}")
        raise
    except Exception as e:
        import traceback
        print(f"Error details: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


@app.post("/api/upload-batch")
async def upload_images_batch(request: Request):
    """
    Upload multiple images and remove their backgrounds in a single request.
    Returns an array of processed images.
    
    Parameters:
    - images: Multiple image files (form field name: "images")
    - backgroundColor: "transparent", "white", or "black"
    - fileType: "PNG" or "JPEG"
    """
    try:
        print("DEBUG: Batch upload endpoint called")
        # Parse form data
        form_data = await request.form()
        
        print(f"DEBUG: form_data keys: {list(form_data.keys())}")
        
        # Get files from form data (multiple files with same field name)
        # In Starlette/FastAPI, getlist() returns a list of values for the key
        files = form_data.getlist("images")
        print(f"DEBUG: Found {len(files) if files else 0} files")
        
        if not files or len(files) == 0:
            print("DEBUG: No files found in form_data")
            raise HTTPException(status_code=400, detail="At least one image file is required")
        
        # Get optional parameters with defaults
        backgroundColor = form_data.get("backgroundColor", "white")
        fileType = form_data.get("fileType", "JPEG")
        watermark = form_data.get("watermark", "none")
        
        # Normalize and validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "white"
        output_format = fileType.upper() if fileType else "JPEG"
        watermark_option = watermark.lower() if watermark else "none"
        
        # Validate parameters
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(status_code=400, detail="backgroundColor must be 'transparent', 'white', or 'black'")
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(status_code=400, detail="fileType must be 'PNG' or 'JPEG'")
        
        if watermark_option not in ["none", "blog"]:
            raise HTTPException(status_code=400, detail="watermark must be 'none' or 'blog'")
        
        # Validate all files are images
        for file in files:
            if not isinstance(file, (UploadFile, StarletteUploadFile)):
                if not hasattr(file, 'read') or not hasattr(file, 'content_type'):
                    raise HTTPException(status_code=400, detail="Invalid file type")
            if not hasattr(file, 'content_type') or not file.content_type or not file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="All files must be images")
        
        print(f"Processing batch of {len(files)} images in parallel")
        start_time = time.time()
        
        # Read all files first (I/O bound, can be parallelized)
        async def read_file_data(file, idx):
            if hasattr(file, 'read'):
                image_data = await file.read()
                filename = getattr(file, 'filename', f'image_{idx}') or f'image_{idx}'
            else:
                image_data = file
                filename = f'image_{idx}'
            return image_data, filename, file
        
        # Read all files in parallel
        file_data_tasks = [read_file_data(file, idx) for idx, file in enumerate(files)]
        file_data_list = await asyncio.gather(*file_data_tasks)
        
        # Process all images in parallel using asyncio.gather
        async def process_with_index(image_data, filename, original_file, idx):
            try:
                # Process the image directly using the sync function in thread pool
                loop = asyncio.get_event_loop()
                processed_image_bytes, mime_type, processed_filename, output_format_final = await loop.run_in_executor(
                    _executor,
                    _process_image_sync,
                    image_data,
                    bg_color,
                    output_format,
                    watermark_option,
                    filename
                )
                
                # Convert to base64 (can be optimized further)
                import base64
                image_base64 = base64.b64encode(processed_image_bytes).decode("utf-8")
                image_url = f"data:{mime_type};base64,{image_base64}"
                
                # Store the processed image
                image_id = f"img_{len(processed_images) + idx}"
                processed_images[image_id] = {
                    "data": processed_image_bytes,
                    "filename": processed_filename,
                    "format": output_format_final,
                    "mime_type": mime_type
                }
                
                return {
                    "imageUrl": image_url,
                    "imageId": image_id,
                    "filename": filename
                }
            except Exception as e:
                import traceback
                error_msg = f"Error processing image {idx + 1} ({filename}): {str(e)}"
                print(error_msg)
                print(traceback.format_exc())
                return {
                    "error": error_msg,
                    "filename": filename
                }
        
        # Process all images in parallel
        processing_tasks = [
            process_with_index(image_data, filename, original_file, idx)
            for idx, (image_data, filename, original_file) in enumerate(file_data_list)
        ]
        results = await asyncio.gather(*processing_tasks)
        
        elapsed_time = time.time() - start_time
        successful = len([r for r in results if 'error' not in r])
        failed = len([r for r in results if 'error' in r])
        print(f"Batch processing completed in {elapsed_time:.2f}s: {successful} successful, {failed} failed ({len(files)/elapsed_time:.2f} images/sec)")
        
        return {
            "results": results,
            "total": len(files),
            "successful": len([r for r in results if 'error' not in r]),
            "failed": len([r for r in results if 'error' in r])
        }
        
    except HTTPException as e:
        print(f"HTTPException: {e.detail}")
        raise
    except Exception as e:
        import traceback
        print(f"Error details: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error processing batch: {str(e)}")


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

def make_checkerboard(w, h, tile=40):
    import numpy as np
    c1 = np.array([200, 200, 200, 255], dtype=np.uint8)
    c2 = np.array([255, 255, 255, 255], dtype=np.uint8)

    board = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            color = c1 if ((x//tile + y//tile) % 2 == 0) else c2
            board[y:y+tile, x:x+tile] = color

    return Image.fromarray(board, 'RGBA')


def add_checkerboard_background(img_with_alpha):
    # Ensure RGBA
    img = img_with_alpha.convert("RGBA")
    w, h = img.size

    # Create checkerboard
    checker = make_checkerboard(w, h)

    # Use alpha channel as mask
    checker.paste(img, (0, 0), mask=img)
    return checker

@app.get("/api/download")
async def download_image(imageId: str = None, fileType: str = None):
    """
    Download the processed image.
    If imageId is provided, returns that specific image.
    Otherwise, returns the most recently processed image.
    
    Parameters:
    - imageId: ID of the image to download
    - fileType: Optional override for file type ("PNG" or "JPEG")
    """
    try:
        image_data = None
        
        if imageId and imageId in processed_images:
            image_data = processed_images[imageId]
        elif processed_images:
            # Return the most recent image
            latest_id = list(processed_images.keys())[-1]
            image_data = processed_images[latest_id]
        else:
            raise HTTPException(status_code=404, detail="No processed image found")
        
        # If fileType is specified, convert the image
        if fileType and fileType.upper() in ["PNG", "JPEG"]:
            output_format = "PNG" if fileType.upper() == "PNG" else "JPEG"
            mime_type = "image/png" if output_format == "PNG" else "image/jpeg"
            
            # Load the stored image
            stored_image = Image.open(io.BytesIO(image_data["data"]))
            
            # Convert format if needed
            if output_format == "JPEG" and stored_image.mode == "RGBA":
                # Convert RGBA to RGB with white background for JPEG
                rgb_image = Image.new("RGB", stored_image.size, (255, 255, 255))
                rgb_image.paste(stored_image, mask=stored_image.split()[3])
                stored_image = rgb_image
            
            # Convert to bytes
            img_byte_arr = io.BytesIO()
            stored_image.save(img_byte_arr, format=output_format, quality=95)
            img_byte_arr.seek(0)
            image_bytes = img_byte_arr.read()
            
            # Update filename extension
            filename = image_data["filename"].rsplit('.', 1)[0]
            extension = "png" if output_format == "PNG" else "jpg"
            filename = f"{filename}.{extension}"
        else:
            # Use stored format
            image_bytes = image_data["data"]
            mime_type = image_data.get("mime_type", "image/png")
            filename = image_data["filename"]
        
        return Response(
            content=image_bytes,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading image: {str(e)}")


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    # Use 127.0.0.1 for development (better Windows compatibility)
    # Use 0.0.0.0 for production (allows external connections)
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    workers = int(os.getenv("WORKERS", 1))  # Number of worker processes
    print(f"Starting server on http://{host}:{port} with {workers} worker(s)")
    uvicorn.run(
        app, 
        host=host, 
        port=port,
        workers=workers,
        timeout_keep_alive=600,  # Increase timeout for batch processing
        limit_concurrency=200,    # Increase concurrent request limit
        limit_max_requests=1000,  # Increase total request limit
        backlog=2048             # Increase connection backlog
    )

