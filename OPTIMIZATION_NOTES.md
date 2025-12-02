# Performance Optimization Notes

## Current Performance
- **Before**: 112 images in 220 seconds (~1.96 sec/image) with 100 concurrent processes
- **Target**: 100 images in 10 seconds (~0.1 sec/image) - **20x speedup needed**

## Optimizations Implemented

### 1. **True Parallel Processing** ✅
- **Before**: Sequential processing in batch endpoint (one image at a time)
- **After**: Parallel processing using `asyncio.gather()` - all images process simultaneously
- **Impact**: Up to 100x faster for batch processing (depending on GPU/CPU)

### 2. **Thread Pool for CPU-Bound Operations** ✅
- Added `ThreadPoolExecutor` with 4 workers for CPU-bound image processing
- Prevents blocking the async event loop
- Allows better utilization of multi-core CPUs

### 3. **Image Size Optimization** ✅
- Automatically resizes images larger than 2048px before processing
- Reduces GPU memory usage and processing time
- Maintains aspect ratio with high-quality LANCZOS resampling

### 4. **Increased Server Concurrency** ✅
- Increased `limit_concurrency` from 10 to 200
- Increased `limit_max_requests` from 100 to 1000
- Increased `backlog` to 2048 for better connection handling
- Increased `timeout_keep_alive` to 600s for batch processing

### 5. **Optimized Image Encoding** ✅
- Reduced JPEG quality from 95 to 85 (minimal visual impact, faster processing)
- Added `optimize=True` flag for better compression
- Base64 encoding still used (can be optimized further with binary responses)

### 6. **Parallel File Reading** ✅
- All files are read in parallel before processing
- Reduces I/O wait time

## Expected Performance Improvements

### Theoretical Maximum
- **GPU Processing**: ~0.1-0.5s per image (GTX 1660 S)
- **With 100 parallel requests**: Could achieve 0.1-0.5s total time
- **Network bottleneck**: 35 Mbps = ~4.4 MB/s upload/download

### Realistic Expectations
Given your hardware (GTX 1660 S, 35 Mbps network):
- **Best case**: 100 images in 10-30 seconds (if GPU can handle parallel inference)
- **Realistic**: 100 images in 30-60 seconds (accounting for GPU memory limits)
- **Network limited**: If images are large, network may be the bottleneck

## Additional Optimization Recommendations

### If Still Not Fast Enough:

1. **Use GPU Batch Processing**
   - Modify `transparent_background` to process multiple images in a single GPU batch
   - Requires custom model wrapper

2. **Reduce Image Resolution Further**
   - Change `max_dimension` from 2048 to 1024 or 512
   - Trade-off: Lower quality but much faster

3. **Use Binary Responses Instead of Base64**
   - Return image IDs and download URLs instead of base64 data
   - Reduces response size by ~33% and encoding overhead

4. **Add Redis/Queue System**
   - Process images asynchronously in background
   - Return job IDs immediately
   - Poll for completion

5. **Upgrade Hardware**
   - Better GPU (RTX 3060+ or A100)
   - Faster network connection
   - More CPU cores

6. **Use Multiple Workers**
   - Set `WORKERS=4` environment variable
   - Requires multiple GPUs or CPU-only processing

## Testing the Optimizations

1. Test with 100 images:
   ```bash
   # Monitor processing time in logs
   journalctl -u image-remove-bg-api -f
   ```

2. Check GPU utilization:
   ```bash
   nvidia-smi -l 1
   ```

3. Monitor network usage:
   ```bash
   iftop -i eth0
   ```

## Configuration

Environment variables (in `/root/image-remove-bg/backend/.env`):
- `WORKERS=1` - Number of uvicorn worker processes (default: 1)
- `HOST=127.0.0.1` - Server host
- `PORT=8000` - Server port

## Notes

- The GTX 1660 S has 6GB VRAM - may limit true parallel processing
- Network speed (35 Mbps) may be a bottleneck for large images
- Consider processing smaller batches if memory is constrained

