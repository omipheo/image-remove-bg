"""
Simple load balancer for multi-GPU setup
Distributes WebSocket connections across 4 GPU workers
Proxies HTTP API requests to the correct worker based on imageId

Requires: pip install websockets httpx
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import asyncio
import json
import os
from typing import List, Optional
import logging
import httpx
import zipfile
import tempfile
import time
import base64

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("WARNING: websockets library not installed. Install with: pip install websockets")

logger = logging.getLogger(__name__)

app = FastAPI(title="Image Background Removal Load Balancer")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend worker URLs (one per GPU)
# These are internal ports - map them to external ports via your port forwarding
WORKER_URLS = [
    "http://127.0.0.1:8001",  # GPU 0 - map external port to this
    "http://127.0.0.1:8002",  # GPU 1 - map external port to this
    "http://127.0.0.1:8003",  # GPU 2 - map external port to this
    "http://127.0.0.1:8004",  # GPU 3 - map external port to this
]

# Round-robin counter
_worker_counter = 0
_worker_lock = asyncio.Lock()

async def get_next_worker():
    """Get next worker URL in round-robin fashion"""
    global _worker_counter
    async with _worker_lock:
        worker_url = WORKER_URLS[_worker_counter]
        _worker_counter = (_worker_counter + 1) % len(WORKER_URLS)
        return worker_url

def get_worker_for_image_id(image_id: str) -> str:
    """
    Extract batch_id from imageId and return the worker URL that processed it.
    ImageId format: img_{batch_id}_{task_id}_{timestamp}
    """
    try:
        # Extract batch_id from imageId
        # Format: img_{batch_id}_{task_id}_{timestamp}
        if image_id.startswith("img_"):
            parts = image_id.split("_")
            if len(parts) >= 2:
                batch_id = int(parts[1])
                worker_index = batch_id % len(WORKER_URLS)
                return WORKER_URLS[worker_index]
    except (ValueError, IndexError):
        pass
    
    # Fallback: use round-robin if we can't parse the imageId
    return WORKER_URLS[0]

@app.get("/")
async def root():
    return {"message": "Image Background Removal Load Balancer", "workers": WORKER_URLS}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "workers": len(WORKER_URLS)}

@app.post("/api/create-zip")
async def create_zip_aggregated(request: Request):
    """
    Create ZIP file by aggregating images from all workers.
    This is necessary because each worker only has its own processed images.
    """
    try:
        body = await request.json()
        batch_ids = body.get("batchIds", None)
        session_id = body.get("sessionId")
        
        logger.info(f"Creating ZIP: session_id={session_id}, batch_ids={batch_ids}")
        
        # Query all workers for their processed images
        all_images = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []
            for worker_url in WORKER_URLS:
                task = client.post(
                    f"{worker_url}/api/get-processed-images",
                    json={"batchIds": batch_ids, "sessionId": session_id},
                    timeout=30.0
                )
                tasks.append((worker_url, task))
            
            # Wait for all workers to respond
            for worker_url, task in tasks:
                try:
                    response = await task
                    if response.status_code == 200:
                        data = response.json()
                        worker_images = data.get("images", {})
                        logger.info(f"Worker {worker_url} returned {len(worker_images)} images")
                        all_images.update(worker_images)
                    else:
                        logger.warning(f"Worker {worker_url} returned status {response.status_code}")
                except Exception as e:
                    logger.error(f"Error querying worker {worker_url}: {e}")
        
        if not all_images:
            logger.warning("No images found from any worker")
            return {
                "zipId": None,
                "imageId": None,
                "downloadUrl": None,
                "success": False,
                "error": "No images found"
            }
        
        logger.info(f"Aggregated {len(all_images)} images from all workers")
        
        # Create ZIP file
        zip_id = f"zip_all_{int(time.time())}"
        tmp_dir = tempfile.gettempdir()
        zip_path = os.path.join(tmp_dir, f"{zip_id}.zip")
        
        image_count = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for image_id, image_data in all_images.items():
                image_bytes = image_data.get("data")
                if image_bytes:
                    # Handle both bytes and base64 strings
                    if isinstance(image_bytes, str):
                        # Try to decode as base64
                        try:
                            image_bytes = base64.b64decode(image_bytes)
                        except:
                            # If not base64, skip this image
                            logger.warning(f"Could not decode image data for {image_id}")
                            continue
                    elif not isinstance(image_bytes, bytes):
                        logger.warning(f"Invalid image data type for {image_id}: {type(image_bytes)}")
                        continue
                    
                    filename = image_data.get("filename", f"{image_id}.jpg")
                    z.writestr(filename, image_bytes)
                    image_count += 1
                    if image_count % 10 == 0:
                        logger.info(f"Added {image_count} images to ZIP...")
        
        logger.info(f"Created ZIP: {zip_path} with {image_count} images")
        
        # Store ZIP on all workers so download can find it from any worker
        storage_success = False
        async with httpx.AsyncClient(timeout=30.0) as client:
            for worker_url in WORKER_URLS:
                try:
                    response = await client.post(
                        f"{worker_url}/api/store-zip",
                        json={"zipId": zip_id, "zipPath": zip_path},
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        logger.info(f"Stored ZIP on worker {worker_url}")
                        storage_success = True
                    else:
                        logger.warning(f"Failed to store ZIP on {worker_url}: {response.status_code}")
                except Exception as e:
                    logger.warning(f"Error storing ZIP on {worker_url}: {e}")
        
        if not storage_success:
            logger.error("Failed to store ZIP on any worker")
            return {
                "zipId": None,
                "imageId": None,
                "downloadUrl": None,
                "success": False,
                "error": "Failed to store ZIP file"
            }
        
        return {
            "zipId": zip_id,
            "imageId": zip_id,
            "downloadUrl": f"/api/download?imageId={zip_id}",
            "success": True,
            "count": image_count
        }
        
    except Exception as e:
        import traceback
        logger.error(f"Error creating ZIP: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating ZIP: {str(e)}"
        )

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_api(request: Request, path: str):
    """
    Proxy API requests to the appropriate worker.
    For /api/download, tries the worker that processed the image based on imageId.
    If not found, tries all other workers as fallback.
    For other endpoints, uses round-robin.
    """
    # Extract query parameters
    query_params = dict(request.query_params)
    image_id = query_params.get("imageId")
    
    # Determine which workers to try
    if image_id and path == "download":
        # For ZIP files, check all workers (ZIPs are stored on all workers)
        if image_id.startswith("zip_"):
            workers_to_try = WORKER_URLS.copy()
            logger.info(f"Routing ZIP download request for imageId={image_id}, checking all workers")
        else:
            # For image downloads, try the expected worker first, then others as fallback
            primary_worker = get_worker_for_image_id(image_id)
            workers_to_try = [primary_worker] + [w for w in WORKER_URLS if w != primary_worker]
            logger.info(f"Routing download request for imageId={image_id}, trying workers: {workers_to_try}")
    else:
        # Round-robin for other requests
        workers_to_try = [await get_next_worker()]
        logger.info(f"Routing API request to worker (round-robin): {workers_to_try[0]}")
    
    # Build base URL parts
    base_path = f"/api/{path}"
    query_string = "&".join([f"{k}={v}" for k, v in query_params.items()]) if query_params else ""
    
    # Try each worker until we get a successful response
    last_error = None
    for worker_url in workers_to_try:
        target_url = f"{worker_url}{base_path}"
        if query_string:
            target_url += f"?{query_string}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get request body if present
                body = None
                if request.method in ["POST", "PUT", "PATCH"]:
                    body = await request.body()
                
                # Forward the request
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers={k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]},
                    content=body,
                    follow_redirects=True
                )
                
                # If successful (2xx or 3xx), return it
                if response.status_code < 400:
                    return Response(
                        content=response.content,
                        status_code=response.status_code,
                        headers={k: v for k, v in response.headers.items() if k.lower() not in ["content-encoding", "transfer-encoding"]},
                        media_type=response.headers.get("content-type")
                    )
                # If 404 and we have more workers to try, continue
                elif response.status_code == 404 and len(workers_to_try) > 1:
                    logger.warning(f"Image not found on {worker_url}, trying next worker...")
                    continue
                else:
                    # Return the error response
                    return Response(
                        content=response.content,
                        status_code=response.status_code,
                        headers={k: v for k, v in response.headers.items() if k.lower() not in ["content-encoding", "transfer-encoding"]},
                        media_type=response.headers.get("content-type")
                    )
        except httpx.TimeoutException:
            logger.warning(f"Timeout proxying request to {target_url}, trying next worker...")
            last_error = "Gateway timeout"
            continue
        except httpx.RequestError as e:
            logger.warning(f"Error proxying request to {target_url}: {e}, trying next worker...")
            last_error = f"Bad gateway: {str(e)}"
            continue
        except Exception as e:
            logger.error(f"Unexpected error proxying request to {target_url}: {e}")
            last_error = f"Internal server error: {str(e)}"
            continue
    
    # If we tried all workers and none worked, return error
    if last_error:
        raise HTTPException(status_code=502, detail=last_error)
    else:
        raise HTTPException(status_code=404, detail="Image not found on any worker")

@app.websocket("/ws/process-images")
async def websocket_load_balancer(websocket: WebSocket):
    """
    Load balance WebSocket connections across GPU workers.
    Uses round-robin to distribute connections.
    """
    if not WEBSOCKETS_AVAILABLE:
        await websocket.close(code=1011, reason="WebSocket library not available")
        return
    
    await websocket.accept()
    
    # Get next worker in round-robin
    worker_url = await get_next_worker()
    worker_ws_url = worker_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/process-images"
    
    logger.info(f"Routing WebSocket connection to worker: {worker_ws_url}")
    
    try:
        # Connect to backend worker using websockets library
        async with websockets.connect(worker_ws_url) as worker_ws:
            # Forward initial config message
            try:
                config_data = await websocket.receive_text()
                await worker_ws.send(config_data)
                
                # Wait for config_ack from worker
                ack_msg = await worker_ws.recv()
                await websocket.send_text(ack_msg)
            except Exception as e:
                logger.error(f"Error forwarding config: {e}")
                return
            
            # Bidirectional message forwarding
            async def forward_to_worker():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await worker_ws.send(msg)
                except WebSocketDisconnect:
                    logger.info("Client disconnected")
                except Exception as e:
                    logger.error(f"Error forwarding to worker: {e}")
            
            async def forward_to_client():
                try:
                    while True:
                        msg = await worker_ws.recv()
                        await websocket.send_text(msg)
                except Exception as e:
                    logger.error(f"Error forwarding to client: {e}")
            
            # Run both forwarding tasks concurrently
            await asyncio.gather(
                forward_to_worker(),
                forward_to_client(),
                return_exceptions=True
            )
                
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Error in load balancer: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Default to 8000 - nginx will proxy 443 -> 8000
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting load balancer on {host}:{port}")
    print(f"Backend workers: {WORKER_URLS}")
    print(f"NOTE: Configure nginx to proxy port 443 -> {host}:{port}")
    uvicorn.run(app, host=host, port=port)

