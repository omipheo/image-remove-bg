#!/bin/bash
# Multi-GPU startup script - starts one process per GPU
# Each process is pinned to a specific GPU via CUDA_VISIBLE_DEVICES

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../venv" ]; then
    source ../venv/bin/activate
fi

# Set CUDA library path
export LD_LIBRARY_PATH=/usr/local/cuda-12.8/targets/x86_64-linux/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Get number of GPUs
NUM_GPUS=$(python3 -c "import torch; print(torch.cuda.device_count() if torch.cuda.is_available() else 0)")
echo "Detected $NUM_GPUS GPU(s)"

if [ "$NUM_GPUS" -eq "0" ]; then
    echo "No GPUs detected, starting single process"
    exec python3 main.py
    exit 0
fi

# Get GPU ID from environment (set by PM2)
GPU_ID=${GPU_ID:-0}
WORKER_PORT=${PORT:-8001}

echo "=== Starting Worker Process ==="
echo "GPU ID: $GPU_ID"
echo "Port: $WORKER_PORT"
echo "CUDA_VISIBLE_DEVICES will be set to: $GPU_ID"

# Pin this process to the specific GPU
export CUDA_VISIBLE_DEVICES=$GPU_ID
export GPU_ID=$GPU_ID
export PORT=$WORKER_PORT

# Start the backend with this GPU
exec python3 main.py

