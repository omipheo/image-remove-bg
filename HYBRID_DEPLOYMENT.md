# Hybrid Deployment Guide: IONOS + RunPod

This guide explains how to deploy the Background Removal Tool using a hybrid architecture:
- **IONOS Server**: Frontend hosting and API gateway
- **RunPod RTX A4000**: GPU-accelerated background removal processing

## Architecture Overview

```
┌─────────────┐
│   Users     │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│      IONOS Server               │
│  ┌──────────┐  ┌─────────────┐ │
│  │ Frontend │  │ API Gateway │ │
│  │ (React)  │  │  (FastAPI)  │ │
│  └──────────┘  └──────┬──────┘ │
└───────────────────────┼────────┘
                        │
                        │ HTTP Request
                        │ (Image + params)
                        ▼
              ┌─────────────────────┐
              │   RunPod RTX A4000   │
              │  GPU Processing      │
              │  (gpu_processor.py)  │
              └─────────────────────┘
                        │
                        │ Processed Image
                        │ (Base64)
                        ▼
              ┌─────────────────────┐
              │   IONOS Server       │
              │   (Returns to user)  │
              └─────────────────────┘
```

## Cost Analysis

### RunPod RTX A4000 Pricing (as of 2025)

#### On-Demand Pods (24/7 running)
- **Community Cloud**: ~$0.17/hour = **~$122/month** (if running 24/7)
- **Secure Cloud**: ~$0.25/hour = **~$180/month** (if running 24/7)
- **Best for**: Consistent, high-volume traffic

#### Serverless (Pay-per-use)
- **Active Workers**: $0.00011/second = **~$0.40/hour** when active
- **Idle Timeout**: No charge when idle
- **FlashBoot**: Faster cold starts
- **Best for**: Intermittent or variable traffic

#### Cost Comparison Examples

**Scenario 1: Low Traffic (100 requests/day, ~5 min processing/day)**
- Serverless: ~$0.03/day = **~$1/month**
- On-Demand: $122/month (wasteful)

**Scenario 2: Medium Traffic (1000 requests/day, ~1 hour processing/day)**
- Serverless: ~$0.40/day = **~$12/month**
- On-Demand: $122/month

**Scenario 3: High Traffic (10,000 requests/day, ~10 hours processing/day)**
- Serverless: ~$4/day = **~$120/month**
- On-Demand: $122/month (more predictable)

**Recommendation**: Start with **Serverless** and switch to **On-Demand** if you consistently use >8 hours/day.

### IONOS Server Costs
- Varies by plan (typically $5-50/month depending on specs)
- No additional cost for this architecture

### Total Monthly Cost Estimate
- **Low Traffic**: $1 (RunPod) + $10 (IONOS) = **~$11/month**
- **Medium Traffic**: $12 (RunPod) + $10 (IONOS) = **~$22/month**
- **High Traffic**: $120 (RunPod) + $20 (IONOS) = **~$140/month**

## Deployment Steps

### Part 1: Deploy GPU Service on RunPod

#### Step 1: Create RunPod Account
1. Sign up at [runpod.io](https://www.runpod.io)
2. Add credits ($10-50 to start)
3. Verify account

#### Step 2: Deploy GPU Service

**Option A: Using RunPod Template (Easiest)**

1. Go to "Pods" → "Deploy Pod"
2. Select:
   - **GPU**: RTX A4000
   - **Template**: RunPod PyTorch 2.1.0
   - **Container Disk**: 20GB
   - **Port**: 8001 (expose publicly)
3. Click "Deploy"
4. Wait for pod to start (2-5 minutes)
5. **Expose Port 8001**:
   - Go to pod → **"Details"** tab
   - Find **"Expose HTTP Ports"** or **"HTTP Ports"** field
   - Add port **8001** to the list
   - **Save** changes (pod will restart)

6. **Get Public URL**:
   - After pod restarts, the HTTP proxy URL format is:
     ```
     https://[POD_ID]-[PORT].proxy.runpod.net
     ```
   - Example: For pod ID `5q4c0f92sj6do3` and port `8001`:
     ```
     https://5q4c0f92sj6do3-8001.proxy.runpod.net
     ```
   - You can verify in **"Connect"** tab → **"HTTP Services"** section
   - ⚠️ **Note**: Don't use "Direct TCP Ports" - that's for SSH, not HTTP!

**Option B: Using Docker Image**

1. Build Docker image:
   ```bash
   docker build -t removebg-gpu:latest -f runpod/Dockerfile .
   docker tag removebg-gpu:latest yourusername/removebg-gpu:latest
   docker push yourusername/removebg-gpu:latest
   ```

2. In RunPod, create pod with:
   - Custom Docker image: `yourusername/removebg-gpu:latest`
   - Port: 8001

#### Step 3: Deploy Code to RunPod

**Via SSH/Terminal:**
```bash
# Connect to RunPod pod (use web terminal or SSH)
cd /workspace
git clone <your-repo-url> removebg
cd removebg/backend

# Install dependencies
pip install -r requirements.txt

# Start service
python gpu_processor.py
```

**Or use the startup script:**
```bash
chmod +x runpod/start.sh
./runpod/start.sh
```

#### Step 4: Configure Environment Variables

In RunPod pod settings, set:
- `HOST=0.0.0.0`
- `PORT=8001`
- `CORS_ORIGINS=https://your-ionos-domain.com` (or `*` for testing)

#### Step 5: Test GPU Service

```bash
curl https://your-runpod-url/health
```

Should return:
```json
{"status": "healthy", "service": "gpu-processor"}
```

### Part 2: Configure IONOS Server

#### Step 1: Update Environment Variables

On your IONOS server, create/update `/var/www/removebg/backend/.env`:

```bash
# Enable remote GPU processing
USE_REMOTE_GPU=true

# Set RunPod GPU service URL
GPU_SERVICE_URL=https://xxxxx-8001.proxy.runpod.net

# CORS (if needed)
CORS_ORIGINS=https://your-domain.com,http://localhost:5173
```

#### Step 2: Update Backend Service

```bash
# SSH into IONOS server
cd /var/www/removebg/backend

# Pull latest code (if using Git)
git pull

# Restart service
sudo systemctl restart removebg-backend

# Check status
sudo systemctl status removebg-backend
```

#### Step 3: Verify Configuration

```bash
# Check API gateway status
curl http://localhost:8000/api/health
```

Should return:
```json
{
  "status": "healthy",
  "mode": "remote-gpu",
  "gpu_service_status": "healthy"
}
```

### Part 3: Update Frontend (if needed)

The frontend should work without changes, but verify the API URL is correct:

```bash
# In frontend/.env.production or GitHub Secrets
VITE_API_BASE_URL=https://your-ionos-domain.com
```

## Configuration Files

### IONOS Server Configuration

**`/var/www/removebg/backend/.env`:**
```env
USE_REMOTE_GPU=true
GPU_SERVICE_URL=https://xxxxx-8001.proxy.runpod.net
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=https://your-domain.com
```

### RunPod Configuration

**Set in RunPod pod environment variables:**
```env
HOST=0.0.0.0
PORT=8001
CORS_ORIGINS=https://your-ionos-domain.com
```

## Testing the Integration

1. **Test GPU Service Directly:**
   ```bash
   curl -X POST https://your-runpod-url/process \
     -F "image=@test-image.jpg" \
     -F "backgroundColor=transparent" \
     -F "fileType=PNG"
   ```

2. **Test via IONOS Gateway:**
   ```bash
   curl -X POST https://your-ionos-domain.com/api/upload \
     -F "image=@test-image.jpg" \
     -F "backgroundColor=transparent" \
     -F "fileType=PNG"
   ```

3. **Test Frontend:**
   - Open your website
   - Upload an image
   - Verify background removal works

## Monitoring

### RunPod Dashboard
- Monitor GPU usage
- View logs
- Check pod status
- Monitor costs

### IONOS Server
```bash
# Check backend logs
sudo journalctl -u removebg-backend -f

# Check API health
curl http://localhost:8000/api/health
```

## Troubleshooting

### GPU Service Not Responding

1. **Check RunPod pod status:**
   - Ensure pod is running
   - Check logs in RunPod dashboard

2. **Verify URL:**
   ```bash
   curl https://your-runpod-url/health
   ```

3. **Check firewall/network:**
   - Ensure port 8001 is exposed
   - Verify CORS settings

### IONOS Can't Connect to RunPod

1. **Check environment variables:**
   ```bash
   cat /var/www/removebg/backend/.env
   ```

2. **Test connection:**
   ```bash
   curl https://your-runpod-url/health
   ```

3. **Check logs:**
   ```bash
   sudo journalctl -u removebg-backend -n 50
   ```

### Performance Issues

1. **RunPod Serverless cold starts:**
   - First request may be slow (30-60 seconds)
   - Consider keeping a worker warm

2. **Network latency:**
   - RunPod and IONOS should be in same region if possible
   - Use RunPod's proxy URL (includes CDN)

3. **GPU utilization:**
   - Monitor in RunPod dashboard
   - Consider scaling if needed

## Cost Optimization Tips

1. **Use Serverless for low/medium traffic**
2. **Switch to On-Demand for high traffic (>8 hours/day)**
3. **Set up auto-scaling** based on queue length
4. **Monitor usage** and adjust accordingly
5. **Use Spot Instances** for non-critical workloads (may be interrupted)

## Security Considerations

1. **API Authentication:**
   - Add API key authentication to RunPod service
   - Use RunPod's built-in authentication

2. **CORS Restrictions:**
   - Only allow your IONOS domain
   - Don't use `*` in production

3. **HTTPS:**
   - Use RunPod's HTTPS proxy
   - Configure SSL on IONOS server

4. **Rate Limiting:**
   - Implement rate limiting on IONOS gateway
   - Prevent abuse

## Switching Between Modes

### Enable Remote GPU:
```bash
# On IONOS server
echo "USE_REMOTE_GPU=true" >> /var/www/removebg/backend/.env
sudo systemctl restart removebg-backend
```

### Disable Remote GPU (use local CPU):
```bash
# On IONOS server
echo "USE_REMOTE_GPU=false" >> /var/www/removebg/backend/.env
sudo systemctl restart removebg-backend
```

## Next Steps

1. Set up monitoring and alerts
2. Implement caching for processed images
3. Add queue system for high traffic
4. Set up auto-scaling
5. Configure backup and disaster recovery

