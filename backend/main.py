from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from PIL import Image
import io
from transparent_background import Remover
import uvicorn
import os
import httpx
import base64

app = FastAPI(title="Image Background Removal API")

# Get CORS origins from environment variable or use defaults
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
).split(",")

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

# Configuration: Use remote GPU processing or local CPU processing
USE_REMOTE_GPU = os.getenv("USE_REMOTE_GPU", "false").lower() == "true"
GPU_SERVICE_URL = os.getenv("GPU_SERVICE_URL", "http://localhost:8001")

# Initialize transparent-background remover (lazy load on first use, only if not using remote GPU)
_remover = None

def get_remover():
    """Lazy load the remover to avoid loading model on startup (only for local processing)"""
    global _remover
    if _remover is None and not USE_REMOTE_GPU:
        _remover = Remover()
    return _remover


async def process_with_remote_gpu(image_data: bytes, bg_color: str, output_format: str, filename: str):
    """
    Send image to remote GPU service for processing
    """
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            files = {"image": (filename or "image.jpg", image_data, "image/jpeg")}
            data = {
                "backgroundColor": bg_color,
                "fileType": output_format
            }
            
            response = await client.post(
                f"{GPU_SERVICE_URL}/process",
                files=files,
                data=data
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GPU service error: {response.text}"
                )
            
            result = response.json()
            if not result.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail="GPU processing failed"
                )
            
            # Decode base64 image
            processed_image_bytes = base64.b64decode(result["image"])
            return processed_image_bytes, result["mime_type"]
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="GPU service timeout - processing took too long"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to GPU service: {str(e)}"
        )


@app.get("/")
async def root():
    return {
        "message": "Image Background Removal API",
        "status": "running",
        "mode": "remote-gpu" if USE_REMOTE_GPU else "local-cpu",
        "gpu_service_url": GPU_SERVICE_URL if USE_REMOTE_GPU else None
    }


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
        backgroundColor = form_data.get("backgroundColor", "transparent")
        fileType = form_data.get("fileType", "PNG")
        
        # Normalize and validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "transparent"
        output_format = fileType.upper() if fileType else "PNG"
        
        # Validate file type
        if not hasattr(file, 'content_type') or not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Validate parameters
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(status_code=400, detail="backgroundColor must be 'transparent', 'white', or 'black'")
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(status_code=400, detail="fileType must be 'PNG' or 'JPEG'")
        
        # Read image file
        image_data = await file.read()
        
        # Determine output format
        output_format = "PNG" if output_format.upper() == "PNG" else "JPEG"
        mime_type = "image/png" if output_format == "PNG" else "image/jpeg"
        
        # Process image: Use remote GPU or local CPU
        if USE_REMOTE_GPU:
            # Send to remote GPU service
            processed_image_bytes, mime_type = await process_with_remote_gpu(
                image_data, bg_color, output_format, file.filename
            )
        else:
            # Local processing (CPU)
            # Load image as PIL Image
            input_image = Image.open(io.BytesIO(image_data))
            
            # Remove background using transparent-background (InSPyReNet)
            remover = get_remover()
            # transparent-background expects PIL Image and returns PIL Image with RGBA
            processed_image = remover.process(input_image, type='rgba')
            
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
            
            processed_image.save(img_byte_arr, format=output_format, quality=95)
            img_byte_arr.seek(0)
            processed_image_bytes = img_byte_arr.read()
        
        # Convert to base64 for frontend
        image_base64 = base64.b64encode(processed_image_bytes).decode("utf-8")
        image_url = f"data:{mime_type};base64,{image_base64}"
        
        # Store the processed image (in production, use proper storage)
        image_id = f"img_{len(processed_images)}"
        file_extension = "png" if output_format == "PNG" else "jpg"
        processed_images[image_id] = {
            "data": processed_image_bytes,
            "filename": (file.filename or "processed_image").rsplit('.', 1)[0] + f"-no-bg.{file_extension}",
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
    gpu_status = "unknown"
    if USE_REMOTE_GPU:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{GPU_SERVICE_URL}/health")
                if response.status_code == 200:
                    gpu_status = "healthy"
                else:
                    gpu_status = "unhealthy"
        except:
            gpu_status = "unreachable"
    
    return {
        "status": "healthy",
        "mode": "remote-gpu" if USE_REMOTE_GPU else "local-cpu",
        "gpu_service_status": gpu_status if USE_REMOTE_GPU else None
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host=host, port=port)

