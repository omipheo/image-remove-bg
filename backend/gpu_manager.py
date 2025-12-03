"""GPU management and Remover instance handling"""
import torch
import threading
from transparent_background import Remover
import os
import gc

# Set PyTorch CUDA allocator config to reduce memory fragmentation
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
print("PyTorch CUDA allocator configured: expandable_segments:True")

# Detect available GPUs
NUM_GPUS = torch.cuda.device_count() if torch.cuda.is_available() else 0
print(f"Detected {NUM_GPUS} GPU(s)")

# Multi-GPU support: Initialize remover instances for each GPU
_removers = {}  # Dictionary: {gpu_id: Remover instance}
_remover_counter = 0  # Round-robin counter for load balancing
_remover_lock = threading.Lock()  # Thread-safe lock for counter
_reset_lock = threading.Lock()  # Lock for GPU reset operations


def get_remover(gpu_id=None):
    """
    Get a remover instance for the specified GPU.
    If gpu_id is None, uses round-robin load balancing across all GPUs.
    Thread-safe for concurrent access.
    """
    global _removers, _remover_counter
    
    # If no GPUs available, use CPU
    if NUM_GPUS == 0:
        if 'cpu' not in _removers:
            try:
                print("Initializing transparent_background Remover on CPU...")
                _removers['cpu'] = Remover(device='cpu')
                print("Remover initialized successfully on CPU")
            except Exception as e:
                print(f"Error initializing Remover: {str(e)}")
                import traceback
                traceback.print_exc()
                raise
        return _removers['cpu']
    
    # Determine which GPU to use (round-robin load balancing)
    if gpu_id is None:
        with _remover_lock:
            gpu_id = _remover_counter % NUM_GPUS
            _remover_counter = (_remover_counter + 1) % NUM_GPUS
    else:
        gpu_id = gpu_id % NUM_GPUS
    
    # Initialize remover for this GPU if not already done
    if gpu_id not in _removers:
        try:
            print(f"Initializing transparent_background Remover on GPU {gpu_id}...")
            _removers[gpu_id] = Remover(device=f'cuda:{gpu_id}')
            print(f"Remover initialized successfully on GPU {gpu_id}")
        except Exception as e:
            print(f"Error initializing Remover on GPU {gpu_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            # Fallback to CPU if GPU fails
            if 'cpu' not in _removers:
                _removers['cpu'] = Remover(device='cpu')
            return _removers['cpu']
    
    return _removers[gpu_id]


def reset_gpu(gpu_id):
    """
    Reset GPU state by clearing memory and optionally recreating Remover instance.
    This helps recover from CUDA illegal memory access errors.
    """
    global _removers
    
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
            
            # Optionally recreate Remover instance if it exists
            # This ensures a clean state
            if gpu_id in _removers:
                try:
                    # Delete old remover to free memory
                    del _removers[gpu_id]
                    _removers[gpu_id] = None
                except:
                    pass
                
                # Clear cache again after deletion
                with torch.cuda.device(gpu_id):
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                
                # Recreate remover instance
                try:
                    print(f"Recreating Remover instance for GPU {gpu_id}...")
                    _removers[gpu_id] = Remover(device=f'cuda:{gpu_id}')
                    print(f"GPU {gpu_id} reset and Remover recreated successfully")
                except Exception as e:
                    print(f"Warning: Could not recreate Remover for GPU {gpu_id}: {e}")
                    # Will be recreated on next get_remover call
            
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

