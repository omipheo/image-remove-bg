"""
GPU Processing Service for RunPod
This service handles background removal on GPU-enabled instances
"""
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io
from transparent_background import Remover
import uvicorn
import os
import base64

app = FastAPI(title="GPU Background Removal Service")

# Configure CORS - allow requests from IONOS server
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "*"  # In production, specify IONOS server IP/domain
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize remover (GPU-enabled)
_remover = None

def get_remover():
    """Lazy load the remover to avoid loading model on startup"""
    global _remover
    if _remover is None:
        print("Loading GPU model...")
        _remover = Remover()
        print("GPU model loaded successfully")
    return _remover


@app.get("/")
async def root():
    return {
        "message": "GPU Background Removal Service",
        "status": "running",
        "gpu": "enabled"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "gpu-processor"}


@app.post("/process")
async def process_image(
    image: UploadFile = File(...),
    backgroundColor: str = Form("transparent"),
    fileType: str = Form("PNG")
):
    """
    Process image background removal on GPU.
    Returns processed image as base64.
    """
    try:
        # Validate parameters
        bg_color = backgroundColor.lower() if backgroundColor else "transparent"
        output_format = fileType.upper() if fileType else "PNG"
        
        if bg_color not in ["transparent", "white", "black"]:
            raise HTTPException(
                status_code=400,
                detail="backgroundColor must be 'transparent', 'white', or 'black'"
            )
        
        if output_format not in ["PNG", "JPEG"]:
            raise HTTPException(
                status_code=400,
                detail="fileType must be 'PNG' or 'JPEG'"
            )
        
        # Read image
        image_data = await image.read()
        input_image = Image.open(io.BytesIO(image_data))
        
        # Process on GPU
        remover = get_remover()
        processed_image = remover.process(input_image, type='rgba')
        
        # Ensure RGBA mode
        if processed_image.mode != 'RGBA':
            processed_image = processed_image.convert('RGBA')
        
        # Apply background color
        if bg_color != "transparent":
            if bg_color == "white":
                bg_rgb = (255, 255, 255)
            else:  # black
                bg_rgb = (0, 0, 0)
            
            background = Image.new("RGB", processed_image.size, bg_rgb)
            background.paste(processed_image, mask=processed_image.split()[3])
            processed_image = background
        
        # Convert to bytes
        output_format = "PNG" if output_format.upper() == "PNG" else "JPEG"
        mime_type = "image/png" if output_format == "PNG" else "image/jpeg"
        
        img_byte_arr = io.BytesIO()
        
        # JPEG doesn't support transparency
        if output_format == "JPEG" and processed_image.mode == "RGBA":
            rgb_image = Image.new("RGB", processed_image.size, (255, 255, 255))
            rgb_image.paste(processed_image, mask=processed_image.split()[3])
            processed_image = rgb_image
        
        processed_image.save(img_byte_arr, format=output_format, quality=95)
        img_byte_arr.seek(0)
        processed_image_bytes = img_byte_arr.read()
        
        # Return as base64
        image_base64 = base64.b64encode(processed_image_bytes).decode("utf-8")
        
        return {
            "success": True,
            "image": image_base64,
            "mime_type": mime_type,
            "format": output_format
        }
        
    except Exception as e:
        import traceback
        print(f"Error processing image: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing image: {str(e)}"
        )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host=host, port=port)

