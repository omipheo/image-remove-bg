# Image Background Removal Backend

Python backend API for removing backgrounds from images using the rembg library.

## Features

- Upload images and automatically remove backgrounds
- Download processed images
- FastAPI with async support
- CORS enabled for frontend integration

## Setup

### 1. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the Server

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Endpoints

### POST `/api/upload`
Upload an image and remove its background.

**Request:**
- Content-Type: `multipart/form-data`
- Body: `file` (image file)

**Response:**
```json
{
  "imageUrl": "data:image/png;base64,...",
  "imageId": "img_0",
  "message": "Background removed successfully"
}
```

### GET `/api/download`
Download the processed image.

**Query Parameters:**
- `imageId` (optional): ID of the image to download. If not provided, returns the most recent image.

**Response:**
- Content-Type: `image/png`
- File download with processed image

### GET `/api/health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy"
}
```

## Technology Stack

- **FastAPI**: Modern, fast web framework for building APIs
- **rembg**: AI-powered background removal library
- **Pillow**: Image processing library
- **Uvicorn**: ASGI server

## Notes

- The rembg library will download AI models on first use (this may take a few minutes)
- Processed images are stored in memory (for production, consider using proper storage)
- The API supports CORS for localhost:5173 (Vite default port)

