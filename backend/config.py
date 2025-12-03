"""Configuration and CORS setup for the API"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_cors_origins():
    """Get CORS origins from environment variable or use defaults"""
    cors_origins_env = os.getenv("CORS_ORIGINS", "")
    if cors_origins_env:
        return cors_origins_env.split(",")
    
    # Default origins including localhost (for SSH port forwarding) and HTTPS
    # Note: Vast.ai uses random public ports, so we include common port patterns
    return [
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


def get_server_config():
    """Get server configuration from environment variables"""
    return {
        "host": os.getenv("HOST", "127.0.0.1"),
        "port": int(os.getenv("PORT", 8000)),
        "workers": int(os.getenv("WORKERS", 1))
    }

