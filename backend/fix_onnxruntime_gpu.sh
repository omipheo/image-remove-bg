#!/bin/bash
# Fix onnxruntime-gpu installation to enable CUDAExecutionProvider

echo "=== Fixing onnxruntime-gpu installation ==="

# Step 1: Uninstall both versions
echo "Uninstalling onnxruntime and onnxruntime-gpu..."
pip uninstall -y onnxruntime onnxruntime-gpu

# Step 2: Reinstall onnxruntime-gpu
echo "Installing onnxruntime-gpu==1.23.2..."
pip install onnxruntime-gpu==1.23.2

# Step 3: Check CUDA library paths
echo ""
echo "=== Checking CUDA libraries ==="
if [ -d "/usr/local/cuda/lib64" ]; then
    echo "Found CUDA at /usr/local/cuda/lib64"
    export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
fi

# Check common CUDA paths
for cuda_path in /usr/local/cuda-*/lib64 /usr/lib/x86_64-linux-gnu; do
    if [ -d "$cuda_path" ] && ls "$cuda_path"/libcudart.so* 1> /dev/null 2>&1; then
        echo "Found CUDA libraries at $cuda_path"
        export LD_LIBRARY_PATH=$cuda_path:$LD_LIBRARY_PATH
    fi
done

# Step 4: Verify installation
echo ""
echo "=== Verifying onnxruntime-gpu installation ==="
python3 -c "
import onnxruntime as ort
providers = ort.get_available_providers()
print('Available providers:', providers)
if 'CUDAExecutionProvider' in providers:
    print('✓ CUDAExecutionProvider is available!')
else:
    print('✗ CUDAExecutionProvider is NOT available')
    print('Available providers:', providers)
"

echo ""
echo "=== Done ==="
echo "If CUDAExecutionProvider is still not available, you may need to:"
echo "1. Check CUDA version compatibility with onnxruntime-gpu 1.23.2"
echo "2. Set LD_LIBRARY_PATH in your environment"
echo "3. Install CUDA toolkit if missing"
