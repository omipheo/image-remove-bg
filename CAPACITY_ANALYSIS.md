# Maximum Concurrent Image Processing Capacity Analysis

## Server Specifications (from Vast.ai)
- **GPU**: GTX 1660 S (6GB VRAM)
- **CPU**: Xeon W-2133 (6 cores, 12 threads)
- **RAM**: 64.2 GB
- **Network**: 870.5 Mbps ↑, 724.1 Mbps ↓
- **Disk**: NVMe, 3054.0 MB/s

## Current GPU Status
- **Total VRAM**: 6144 MiB (6GB)
- **Free VRAM**: 236 MiB (model loaded, using ~5.9GB)
- **Model Size**: ~5.9GB (transparent-background model)

## Bottleneck Analysis

### 1. GPU VRAM (Primary Bottleneck)
- **Model footprint**: ~5.9GB (already loaded)
- **Available for processing**: ~236 MB free
- **Per-image VRAM usage** (2048px max):
  - Input tensor: ~16-32 MB
  - Processing buffers: ~50-100 MB
  - Output tensor: ~16-32 MB
  - **Total per image**: ~100-200 MB

**Theoretical GPU parallel capacity**: 
- With 236 MB free: **1-2 images truly in parallel on GPU**
- However, `transparent-background` processes images sequentially on GPU
- **Actual GPU throughput**: ~1 image at a time (sequential)

### 2. CPU Processing (Secondary)
- **Cores**: 6 physical, 12 threads
- **Thread pool workers**: 4 (current config)
- **CPU can handle**: Many parallel tasks (I/O, encoding, etc.)
- **Not the bottleneck** for GPU inference

### 3. Network (If Fastest)
- **Upload**: 870.5 Mbps = ~109 MB/s
- **Download**: 724.1 Mbps = ~90.5 MB/s
- **Per image** (2048px JPEG): ~0.06-2 MB (compressed)
- **Network capacity**: Can handle **hundreds of images/second** for upload/download
- **Not a bottleneck** if network is fastest

### 4. Memory (RAM)
- **Available**: 64.2 GB
- **Per image in memory**: ~10-50 MB (uncompressed)
- **Capacity**: Can hold **thousands of images** in memory
- **Not a bottleneck**

## Maximum Concurrent Processing

### Current Implementation
- **Thread pool**: 4 workers
- **Async concurrency**: Unlimited (asyncio.gather)
- **GPU processing**: Sequential (1 image at a time on GPU)

### Realistic Maximum (Network Not a Bottleneck)

**Scenario 1: True GPU Parallelism (if model supported it)**
- Available VRAM: 236 MB
- Per image: ~150 MB
- **Maximum**: **1-2 images** truly parallel on GPU

**Scenario 2: Current Sequential GPU Processing**
- GPU processes: **1 image at a time**
- Processing time: ~0.5-2 seconds per image (GTX 1660 S)
- **Concurrent requests**: Can accept **unlimited** requests
- **Actual GPU throughput**: ~0.5-2 images/second

**Scenario 3: Optimized with Batching**
- If we batch multiple images into single GPU inference:
  - Batch size limited by VRAM: **1-2 images per batch**
  - **Maximum concurrent**: Still **1-2 images** per GPU inference

## Answer: Maximum Concurrent Images

### If Network is Fastest (Not a Bottleneck):

**Theoretical Maximum**: 
- **GPU can process**: **1-2 images truly in parallel** (VRAM limited)
- **But transparent-background processes sequentially**: **1 image at a time on GPU**

**Practical Maximum**:
- **Concurrent requests accepted**: **Unlimited** (server can queue)
- **GPU processing rate**: **~0.5-2 images/second** (GTX 1660 S performance)
- **With 100 concurrent requests**: All queued, processed sequentially
- **Time for 100 images**: ~50-200 seconds (GPU bound)

### If You Want True Parallelism:

**Option 1: Reduce Image Size**
- Change `max_dimension` from 2048 to 512 or 1024
- Reduces VRAM per image: ~25-50 MB
- Could process: **4-8 images in parallel** (if model supported batching)

**Option 2: Use Multiple GPUs**
- Not available on this instance (single GPU)

**Option 3: CPU Processing**
- Much slower (~10-50x slower than GPU)
- Can process many in parallel (limited by CPU cores)
- Not recommended for production

## Conclusion

**Maximum concurrent images the server can process at once (if network is fastest):**

1. **True GPU parallel processing**: **1-2 images** (VRAM limited, model doesn't support batching)
2. **Concurrent requests accepted**: **Unlimited** (all queued, processed sequentially)
3. **GPU throughput**: **~0.5-2 images/second** (GTX 1660 S performance)

**For 100 images with network as fastest:**
- All 100 requests accepted immediately
- Processed sequentially by GPU
- Total time: **~50-200 seconds** (GPU bound, not network bound)

**To achieve 100 images in 10 seconds:**
- Would need: **10 images/second GPU throughput**
- Current GPU: **0.5-2 images/second**
- **Required**: 5-20x faster GPU (RTX 3090, A100, etc.) OR
- **Required**: True batch processing support in the model

