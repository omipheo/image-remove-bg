"""GPU management and rembg session handling"""
import torch
import threading
from rembg import new_session, remove
import os
import gc

# Set PyTorch CUDA allocator config to reduce memory fragmentation
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
print("PyTorch CUDA allocator configured: expandable_segments:True")

# Detect available GPUs
NUM_GPUS = torch.cuda.device_count() if torch.cuda.is_available() else 0
print(f"Detected {NUM_GPUS} GPU(s)")

# Multi-GPU support: Initialize rembg sessions for each GPU
_sessions = {}  # Dictionary: {gpu_id: rembg session}
_session_counter = 0  # Round-robin counter for load balancing
_session_lock = threading.Lock()  # Thread-safe lock for counter
_reset_lock = threading.Lock()  # Lock for GPU reset operations

# rembg model to use (u2net is default, supports GPU well)
REMBG_MODEL = os.getenv("REMBG_MODEL", "u2net")  # Options: u2net, u2net_human_seg, silueta, isnet-general-use


def get_session(gpu_id=None):
    """
    Get a rembg session for the specified GPU.
    If gpu_id is None, uses round-robin load balancing across all GPUs.
    Thread-safe for concurrent access.
    Sessions can be reused for multiple images (batch processing).
    """
    global _sessions, _session_counter
    
    # If no GPUs available, use CPU
    if NUM_GPUS == 0:
        if 'cpu' not in _sessions:
            try:
                print(f"Initializing rembg session on CPU (model: {REMBG_MODEL})...")
                _sessions['cpu'] = new_session(REMBG_MODEL)
                print("rembg session initialized successfully on CPU")
            except Exception as e:
                print(f"Error initializing rembg session: {str(e)}")
                import traceback
                traceback.print_exc()
                raise
        return _sessions['cpu']
    
    # Determine which GPU to use (round-robin load balancing)
    if gpu_id is None:
        with _session_lock:
            gpu_id = _session_counter % NUM_GPUS
            _session_counter = (_session_counter + 1) % NUM_GPUS
    else:
        gpu_id = gpu_id % NUM_GPUS
    
    # Initialize session for this GPU if not already done
    if gpu_id not in _sessions:
        try:
            print(f"Initializing rembg session on GPU {gpu_id} (model: {REMBG_MODEL})...")
            # rembg automatically uses GPU if available via ONNX Runtime
            # We can specify providers for GPU acceleration
            _sessions[gpu_id] = new_session(REMBG_MODEL)
            print(f"rembg session initialized successfully on GPU {gpu_id}")
        except Exception as e:
            print(f"Error initializing rembg session on GPU {gpu_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            # Fallback to CPU if GPU fails
            if 'cpu' not in _sessions:
                _sessions['cpu'] = new_session(REMBG_MODEL)
            return _sessions['cpu']
    
    return _sessions[gpu_id]


# Alias for backward compatibility
def get_remover(gpu_id=None):
    """Alias for get_session() for backward compatibility"""
    return get_session(gpu_id)


def reset_gpu(gpu_id):
    """
    Reset GPU state by clearing memory and optionally recreating rembg session.
    This helps recover from CUDA illegal memory access errors.
    """
    global _sessions
    
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
            
            # Optionally recreate session instance if it exists
            # This ensures a clean state
            if gpu_id in _sessions:
                try:
                    # Delete old session to free memory
                    del _sessions[gpu_id]
                    _sessions[gpu_id] = None
                except:
                    pass
                
                # Clear cache again after deletion
                with torch.cuda.device(gpu_id):
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                
                # Recreate session instance
                try:
                    print(f"Recreating rembg session for GPU {gpu_id}...")
                    _sessions[gpu_id] = new_session(REMBG_MODEL)
                    print(f"GPU {gpu_id} reset and rembg session recreated successfully")
                except Exception as e:
                    print(f"Warning: Could not recreate rembg session for GPU {gpu_id}: {e}")
                    # Will be recreated on next get_session call
            
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

