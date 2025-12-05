"""Main FastAPI application entry point"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

from config import get_cors_origins, get_server_config
from routes import router
from workers import start_workers, stop_workers

# Create FastAPI app
app = FastAPI(title="Image Background Removal API")

# Configure CORS
cors_origins = get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


# Startup event: Start background workers
@app.on_event("startup")
async def startup_event():
    """Start background GPU workers for continuous processing"""
    await start_workers()


# Shutdown event: Stop background workers
@app.on_event("shutdown")
async def shutdown_event():
    """Stop background GPU workers"""
    await stop_workers()


if __name__ == "__main__":
    # Get server configuration
    config = get_server_config()
    host = config["host"]
    port = config["port"]
    workers = config["workers"]
    
    print(f"Starting server on http://{host}:{port} with {workers} worker(s)")
    uvicorn.run(
        app, 
        host=host, 
        port=port,
        workers=workers,
        timeout_keep_alive=600,  # Increase timeout for batch processing
        limit_concurrency=200,    # Increase concurrent request limit
        backlog=2048             # Increase connection backlog
    )
