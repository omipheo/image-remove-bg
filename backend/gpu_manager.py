"""GPU management and withoutbg instance handling"""
import torch
import threading
from withoutbg import WithoutBG
import onnxruntime as ort
import os
import gc

# Set PyTorch CUDA allocator config to reduce memory fragmentation
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
print("PyTorch CUDA allocator configured: expandable_segments:True")

# Patch withoutbg to use GPU instead of CPU
# The library is hardcoded to use CPUExecutionProvider, so we need to patch it
def _patch_withoutbg_for_gpu():
    """Patch withoutbg models to use CUDA if available"""
    try:
        import withoutbg.models as wb_models
        
        # Check if CUDA is available
        cuda_available = 'CUDAExecutionProvider' in ort.get_available_providers()
        
        if cuda_available:
            # Store original method
            original_load = wb_models.OpenSourceModel._load_models
            
            def _load_models_gpu(self):
                """Load models with GPU support"""
                try:
                    # Use CUDA if available, fallback to CPU
                    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                    
                    # Load Depth Anything V2 model
                    self.depth_session = ort.InferenceSession(
                        str(self.depth_model_path), providers=providers
                    )
                    
                    # Load ISNet segmentation model
                    self.isnet_session = ort.InferenceSession(
                        str(self.isnet_model_path), providers=providers
                    )
                    
                    # Load Matting model
                    self.matting_session = ort.InferenceSession(
                        str(self.matting_model_path), providers=providers
                    )
                    
                    # Load Refiner model
                    self.refiner_session = ort.InferenceSession(
                        str(self.refiner_model_path), providers=providers
                    )
                    
                except Exception as e:
                    raise wb_models.ModelNotFoundError(f"Failed to load models: {str(e)}") from e
            
            # Apply patch
            wb_models.OpenSourceModel._load_models = _load_models_gpu
            print("✓ Patched withoutbg to use GPU acceleration")
        else:
            print("⚠ CUDA not available in ONNX Runtime, using CPU")
    except Exception as e:
        print(f"⚠ Warning: Could not patch withoutbg for GPU: {e}")
        print("  Continuing with CPU execution")

# Apply patch on import
_patch_withoutbg_for_gpu()

# Detect available GPUs
NUM_GPUS = torch.cuda.device_count() if torch.cuda.is_available() else 0
print(f"Detected {NUM_GPUS} GPU(s)")

# Multi-GPU support: Initialize withoutbg instances for each GPU
_instances = {}  # Dictionary: {gpu_id: WithoutBG instance}
_instance_counter = 0  # Round-robin counter for load balancing
_instance_lock = threading.Lock()  # Thread-safe lock for counter
_reset_lock = threading.Lock()  # Lock for GPU reset operations


def get_instance(gpu_id=None):
    """
    Get a withoutbg instance for the specified GPU.
    If gpu_id is None, uses round-robin load balancing across all GPUs.
    Thread-safe for concurrent access.
    Instances can be reused for multiple images and support batch processing.
    """
    global _instances, _instance_counter
    
    # If no GPUs available, use CPU
    if NUM_GPUS == 0:
        if 'cpu' not in _instances:
            try:
                print("Initializing withoutbg instance on CPU...")
                _instances['cpu'] = WithoutBG.opensource()
                print("withoutbg instance initialized successfully on CPU")
            except Exception as e:
                print(f"Error initializing withoutbg instance: {str(e)}")
                import traceback
                traceback.print_exc()
                raise
        return _instances['cpu']
    
    # Determine which GPU to use (round-robin load balancing)
    if gpu_id is None:
        with _instance_lock:
            gpu_id = _instance_counter % NUM_GPUS
            _instance_counter = (_instance_counter + 1) % NUM_GPUS
    else:
        gpu_id = gpu_id % NUM_GPUS
    
    # Initialize instance for this GPU if not already done
    if gpu_id not in _instances:
        try:
            print(f"Initializing withoutbg instance on GPU {gpu_id}...")
            # withoutbg automatically uses GPU if available
            _instances[gpu_id] = WithoutBG.opensource()
            print(f"withoutbg instance initialized successfully on GPU {gpu_id}")
        except Exception as e:
            print(f"Error initializing withoutbg instance on GPU {gpu_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            # Fallback to CPU if GPU fails
            if 'cpu' not in _instances:
                _instances['cpu'] = WithoutBG.opensource()
            return _instances['cpu']
    
    return _instances[gpu_id]


# Alias for backward compatibility
def get_session(gpu_id=None):
    """Alias for get_instance() for backward compatibility"""
    return get_instance(gpu_id)


# Alias for backward compatibility
def get_remover(gpu_id=None):
    """Alias for get_instance() for backward compatibility"""
    return get_instance(gpu_id)


def reset_gpu(gpu_id):
    """
    Reset GPU state by clearing memory and optionally recreating withoutbg instance.
    This helps recover from CUDA illegal memory access errors.
    """
    global _instances
    
    if gpu_id is None or NUM_GPUS == 0:
        return
    
    with _reset_lock:
        try:
            print(f"Resetting GPU {gpu_id} to recover from memory corruption...")
            
            # Set device context
            torch.cuda.set_device(gpu_id)
            
            # Clear all CUDA cache
            with torch.cuda.device(gpu_id):
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                torch.cuda.ipc_collect()  # Clear IPC resources
            
            # Force garbage collection
            gc.collect()
            
            # Optionally recreate instance if it exists
            # This ensures a clean state
            if gpu_id in _instances:
                try:
                    # Delete old instance to free memory
                    del _instances[gpu_id]
                    _instances[gpu_id] = None
                except:
                    pass
                
                # Clear cache again after deletion
                with torch.cuda.device(gpu_id):
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                
                # Recreate instance
                try:
                    print(f"Recreating withoutbg instance for GPU {gpu_id}...")
                    _instances[gpu_id] = WithoutBG.opensource()
                    print(f"GPU {gpu_id} reset and withoutbg instance recreated successfully")
                except Exception as e:
                    print(f"Warning: Could not recreate withoutbg instance for GPU {gpu_id}: {e}")
                    # Will be recreated on next get_instance call
            
            print(f"GPU {gpu_id} reset complete")
            
        except Exception as e:
            print(f"Error resetting GPU {gpu_id}: {e}")
            import traceback
            traceback.print_exc()


def reset_all_gpus():
    """Reset all GPUs to recover from memory corruption"""
    if NUM_GPUS == 0:
        return
    
    print("Resetting all GPUs to recover from memory corruption...")
    for gpu_id in range(NUM_GPUS):
        reset_gpu(gpu_id)
    print("All GPUs reset complete")

