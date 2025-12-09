#!/bin/bash
# Startup script for backend with proper CUDA environment

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d "../venv" ]; then
    source ../venv/bin/activate
fi

# Set CUDA library path
export LD_LIBRARY_PATH=/usr/local/cuda-12.8/targets/x86_64-linux/lib:$LD_LIBRARY_PATH

# Additional CUDA paths
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Print environment info
echo "=== Backend Startup Environment ==="
echo "Python: $(which python3)"
echo "CUDA Library Path: $LD_LIBRARY_PATH"
echo "Virtual Env: $VIRTUAL_ENV"

# Verify onnxruntime-gpu
python3 -c "import onnxruntime as ort; providers = ort.get_available_providers(); print('ONNX Runtime Providers:', providers); assert 'CUDAExecutionProvider' in providers, 'CUDAExecutionProvider not available!'"

# Start the backend
cd "$(dirname "$0")"
exec python3 main.py
