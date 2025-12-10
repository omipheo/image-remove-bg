from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request, WebSocket
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from PIL import Image
import io
import uvicorn
import os
from dotenv import load_dotenv
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import base64

# GPU-based processing imports
from image_processor import process_image_sync, initialize_model_pool
from workers import get_batch_queue, start_batch_processor
from gpu_manager import NUM_GPUS

# Load environment variables from .env file
load_dotenv()

from contextlib import asynccontextmanager

# Import the NEW parallel websocket handler
from websocket_handler import websocket_endpoint

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    # Startup
    start_batch_processor()
    initialize_model_pool()
    print(f"Backend started with {NUM_GPUS} GPU(s) available")
    yield
    # Shutdown (if needed)
    pass

app = FastAPI(title="Image Background Removal API", lifespan=lifespan)

# Get CORS origins from environment variable or use defaults
cors_origins_str = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
)
# Split by comma and strip whitespace
cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

# Log CORS origins for debugging
print(f"CORS Origins configured: {cors_origins}")

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

# Thread pool for GPU-bound operations (runs in executor)
_executor = ThreadPoolExecutor(max_workers=min(32, NUM_GPUS * 8) if NUM_GPUS > 0 else 4)

async def process_single_image(file, bg_color, output_format, watermark_option):
    """
    Process a single image: remove background, apply color, and watermark.
    Returns processed image bytes, mime_type, and filename.
    Uses GPU via thread pool executor.
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
    
    # Run GPU processing in thread pool (process_image_sync handles GPU)
    loop = asyncio.get_event_loop()
    processed_image_bytes, mime_type, processed_filename, output_format_final = await loop.run_in_executor(
        _executor,
        process_image_sync,
        image_data,
        bg_color,
        output_format,
        watermark_option,
        filename,
        None  # gpu_id=None for round-robin
    )
    
    return processed_image_bytes, mime_type, processed_filename, output_format_final

@app.get("/")
async def root():
    return {"message": "Image Background Removal API", "status": "running"}

# ✅ NEW PARALLEL WEBSOCKET ENDPOINT
@app.websocket("/ws/process-images")
async def websocket_route(websocket: WebSocket):
    """WebSocket endpoint for parallel batch processing"""
    await websocket_endpoint(websocket)


@app.post("/api/upload")
async def upload_image(request: Request):
    """
    Upload an image and remove its background.
    Returns the processed image as base64 or URL.
    
    Parameters:
    - backgroundColor: "transparent", "white", or "black"
    - fileType: "PNG" or "JPEG"
    """
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
        
        # Process the image using GPU
        processed_image_bytes, mime_type, processed_filename, output_format = await process_single_image(
            file, bg_color, output_format, watermark_option
        )
        
        # Convert to base64 for frontend
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
            "mime_type": mime_type,
            "pre_uploaded": True  # Mark as pre-uploaded via /api/upload
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

@app.get("/api/download")
async def download_image(imageId: str = None, fileType: str = None):
    """
    Download the processed image or zip file.
    If imageId is provided, returns that specific image or zip file.
    Otherwise, returns the most recently processed image.
    
    Parameters:
    - imageId: ID of the image/zip to download (e.g., "img_xxx" or "zip_xxx")
    - fileType: Optional override for file type ("PNG" or "JPEG") - only for images
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
        
        # Handle zip files
        if imageId and imageId.startswith("zip_") and "file_path" in image_data:
            zip_path = image_data["file_path"]
            if os.path.exists(zip_path):
                with open(zip_path, 'rb') as f:
                    zip_bytes = f.read()
                return Response(
                    content=zip_bytes,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f'attachment; filename="{image_data["filename"]}"'
                    }
                )
            else:
                raise HTTPException(status_code=404, detail="Zip file not found")
        
        # Handle regular images
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