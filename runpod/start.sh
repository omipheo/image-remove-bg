#!/bin/bash

# RunPod Startup Script for GPU Processing Service
# This script runs when the RunPod pod starts

echo "Starting GPU Processing Service..."

# Navigate to the application directory
cd /workspace/removebg/backend || cd /app/backend || exit

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Set environment variables
export HOST=0.0.0.0
export PORT=8001
export CORS_ORIGINS="${IONOS_SERVER_URL:-*}"

# Start the GPU processing service
echo "Starting GPU service on port $PORT..."
python gpu_processor.py

