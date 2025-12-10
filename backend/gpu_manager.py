"""
GPU Manager - Handles GPU detection, initialization, and transparent_background library setup for GPU usage.
Enforces GPU-only operation - no CPU fallback.
"""
import torch
import onnxruntime
import os
import sys
import ctypes
import glob

# Global GPU count
NUM_GPUS = 0
_gpu_instances = {}  # {gpu_id: Remover instance}
_gpu_counter = 0  # For round-robin assignment

def _setup_cuda_library_path():
    """
    Try to find and add CUDA libraries to LD_LIBRARY_PATH if not already set.
    """
    # Check if CUDA libraries are already accessible
    try:
        ctypes.CDLL('libcudart.so')
        return  # CUDA libraries are accessible
    except OSError:
        pass
    
    # Common CUDA library paths
    cuda_paths = [
        '/usr/local/cuda-12.8/targets/x86_64-linux/lib',  # Your specific CUDA path
        '/usr/local/cuda/lib64',
        '/usr/local/cuda-12/lib64',
        '/usr/local/cuda-11/lib64',
        '/usr/lib/x86_64-linux-gnu',
    ]
    
    # Also check for versioned CUDA directories
    for path in glob.glob('/usr/local/cuda-*/lib64'):
        cuda_paths.append(path)
    for path in glob.glob('/usr/local/cuda-*/targets/x86_64-linux/lib'):
        cuda_paths.append(path)
    
    # Find CUDA libraries
    for cuda_path in cuda_paths:
        if os.path.exists(cuda_path):
            libcudart = os.path.join(cuda_path, 'libcudart.so')
            if os.path.exists(libcudart) or glob.glob(os.path.join(cuda_path, 'libcudart.so.*')):
                # Add to LD_LIBRARY_PATH
                current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
                if cuda_path not in current_ld_path:
                    os.environ['LD_LIBRARY_PATH'] = f"{cuda_path}:{current_ld_path}" if current_ld_path else cuda_path
                    print(f"Added CUDA library path to LD_LIBRARY_PATH: {cuda_path}")
                    # Try to load the library
                    try:
                        ctypes.CDLL(os.path.join(cuda_path, 'libcudart.so'))
                        print(f"Successfully loaded CUDA runtime from {cuda_path}")
                        return
                    except OSError:
                        pass

def _patch_transparent_background_for_gpu():
    """
    Patch the transparent_background library to use GPU (CUDAExecutionProvider) instead of CPU.
    This must be called before importing or using Remover.
    """
    try:
        # Try to set up CUDA library paths
        _setup_cuda_library_path()
        
        # Check if CUDAExecutionProvider is available
        available_providers = onnxruntime.get_available_providers()
        cuda_available = 'CUDAExecutionProvider' in available_providers
        
        if not cuda_available:
            # Enhanced error message with diagnostics
            torch_cuda_available = torch.cuda.is_available()
            torch_cuda_count = torch.cuda.device_count() if torch_cuda_available else 0
            
            error_msg = (
                "CUDAExecutionProvider is not available in ONNX Runtime. "
                "GPU is required for this application.\n"
                f"Available ONNX Runtime providers: {available_providers}\n"
                f"PyTorch CUDA available: {torch_cuda_available}\n"
                f"PyTorch CUDA device count: {torch_cuda_count}\n"
                "Please ensure:\n"
                "1. onnxruntime-gpu is installed (not onnxruntime): pip install onnxruntime-gpu\n"
                "2. CUDA libraries are properly installed and accessible\n"
                "3. LD_LIBRARY_PATH includes CUDA library paths if needed\n"
                "4. Check nvidia-smi to verify GPU is accessible"
            )
            raise RuntimeError(error_msg)
        
        # Patch transparent_background's internal ONNX Runtime session creation if needed
        try:
            import transparent_background
            
            # Check if it uses onnxruntime.InferenceSession, we can patch it
            original_inference_session = onnxruntime.InferenceSession
            
            def patched_inference_session(*args, **kwargs):
                # Force CUDA provider if providers not explicitly set
                if 'providers' not in kwargs:
                    kwargs['providers'] = ['CUDAExecutionProvider']
                elif 'CUDAExecutionProvider' not in kwargs['providers']:
                    # Prepend CUDA provider
                    kwargs['providers'] = ['CUDAExecutionProvider'] + kwargs['providers']
                return original_inference_session(*args, **kwargs)
            
            # Apply patch
            onnxruntime.InferenceSession = patched_inference_session
            print("Successfully patched transparent_background for GPU usage (CUDAExecutionProvider)")
        except ImportError:
            # transparent_background may not use onnxruntime, or uses it differently
            print("Note: transparent_background may use PyTorch directly for GPU")
        
        return True
        
    except Exception as e:
        error_msg = f"Failed to patch transparent_background for GPU: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        raise RuntimeError(error_msg)

def initialize_gpus():
    """
    Initialize GPU detection and patching. Must be called at startup.
    Raises RuntimeError if GPU is not available (GPU-only mode).
    """
    global NUM_GPUS
    
    # Patch transparent_background first, before any Remover instances are created
    _patch_transparent_background_for_gpu()
    
    # Detect available GPUs - GPU REQUIRED
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is not available in PyTorch. GPU is required for this application. "
            "Please ensure PyTorch with CUDA support is installed and CUDA drivers are available."
        )
    
    NUM_GPUS = torch.cuda.device_count()
    if NUM_GPUS == 0:
        raise RuntimeError(
            "No GPUs detected. GPU is required for this application. "
            "Please check nvidia-smi to verify GPU availability."
        )
    
    print(f"GPU initialization successful: {NUM_GPUS} GPU(s) detected")
    for i in range(NUM_GPUS):
        print(f"  GPU {i}: {torch.cuda.get_device_name(i)}")
    
    return NUM_GPUS

def get_instance(gpu_id=None):
    """
    Get a Remover instance for the specified GPU, or round-robin if gpu_id is None.
    
    Args:
        gpu_id: GPU ID (0 to NUM_GPUS-1) or None for round-robin assignment
    
    Returns:
        Remover instance configured for GPU
    
    Raises:
        RuntimeError: If no GPUs available or initialization fails
    """
    global NUM_GPUS, _gpu_instances, _gpu_counter
    
    if NUM_GPUS == 0:
        raise RuntimeError("No GPUs available - GPU is required for image processing")
    
    # Round-robin assignment if gpu_id is None
    if gpu_id is None:
        gpu_id = _gpu_counter % NUM_GPUS
        _gpu_counter += 1
    
    # Validate GPU ID
    if gpu_id < 0 or gpu_id >= NUM_GPUS:
        raise ValueError(f"Invalid GPU ID: {gpu_id}. Must be between 0 and {NUM_GPUS - 1}")
    
    # Get or create instance for this GPU
    if gpu_id not in _gpu_instances:
        try:
            # Set CUDA device before creating instance
            torch.cuda.set_device(gpu_id)
            
            # Create Remover instance for transparent_background
            from transparent_background import Remover
            instance = Remover(device=f'cuda:{gpu_id}')
            
            _gpu_instances[gpu_id] = instance
            print(f"Created Remover instance for GPU {gpu_id}")
        except Exception as e:
            error_msg = f"Failed to create Remover instance for GPU {gpu_id}: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            raise RuntimeError(error_msg)
    
    return _gpu_instances[gpu_id]

def reset_gpu(gpu_id):
    """
    Reset GPU memory for a specific GPU.
    
    Args:
        gpu_id: GPU ID to reset
    
    Raises:
        RuntimeError: If no GPUs available
    """
    if NUM_GPUS == 0:
        raise RuntimeError("No GPUs available - GPU is required")
    
    if gpu_id < 0 or gpu_id >= NUM_GPUS:
        raise ValueError(f"Invalid GPU ID: {gpu_id}")
    
    try:
        with torch.cuda.device(gpu_id):
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception as e:
        print(f"Warning: Failed to reset GPU {gpu_id}: {str(e)}")

def reset_all_gpus():
    """
    Reset memory for all GPUs.
    
    Raises:
        RuntimeError: If no GPUs available
    """
    if NUM_GPUS == 0:
        raise RuntimeError("No GPUs available - GPU is required")
    
    for gpu_id in range(NUM_GPUS):
        reset_gpu(gpu_id)

# Initialize GPUs at module import
try:
    initialize_gpus()
except RuntimeError as e:
    print(f"CRITICAL: GPU initialization failed: {str(e)}")
    sys.exit(1)