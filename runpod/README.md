# RunPod GPU Processing Service

This directory contains configuration files for deploying the GPU processing service on RunPod.

## RunPod Setup

### Option 1: Using RunPod Template (Recommended)

1. **Create a RunPod Account**
   - Sign up at [runpod.io](https://www.runpod.io)
   - Add credits to your account

2. **Create a Pod with RTX A4000**
   - Go to "Pods" → "Deploy Pod"
   - Select GPU: **RTX A4000**
   - Select Template: **RunPod PyTorch 2.1.0**
   - Configure:
     - Container Image: Use the Dockerfile in this directory or use a base image
     - Container Disk: 20GB minimum
     - Volume: Optional (for persistent storage)
     - Port: **8001** (expose this port)

3. **Expose Port 8001**
   - In pod settings, go to "Connect" tab
   - Under "HTTP Services", expose port **8001**
   - Wait for pod to restart if needed

4. **Get Public URL**
   - After port is exposed, check "HTTP Services" section
   - You'll see the HTTP proxy URL (e.g., `https://xxxxx-8001.proxy.runpod.net`)
   - ⚠️ **Important**: Use the HTTP Services URL, NOT the Direct TCP Ports (those are for SSH)

5. **Deploy Code**
   ```bash
   # SSH into the pod or use the web terminal
   cd /workspace
   git clone <your-repo-url> removebg
   cd removebg/backend
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Start the service
   python gpu_processor.py
   ```

### Option 2: Using Docker Image

1. **Build Docker Image** (on your local machine or CI/CD)
   ```bash
   docker build -t removebg-gpu:latest -f runpod/Dockerfile .
   ```

2. **Push to Docker Hub or Container Registry**
   ```bash
   docker tag removebg-gpu:latest yourusername/removebg-gpu:latest
   docker push yourusername/removebg-gpu:latest
   ```

3. **Deploy on RunPod**
   - Create pod with custom Docker image: `yourusername/removebg-gpu:latest`
   - Expose port 8001
   - Set environment variables:
     - `HOST=0.0.0.0`
     - `PORT=8001`
     - `CORS_ORIGINS=https://your-ionos-domain.com`

### Option 3: Using RunPod Serverless (Cost-Effective)

For intermittent usage, consider RunPod Serverless:

1. **Create Serverless Endpoint**
   - Go to "Serverless" → "Create Endpoint"
   - Select GPU: RTX A4000
   - Use the Dockerfile or container image
   - Set handler: `gpu_processor.py`

2. **Configure**
   - Max Workers: 1-5 (depending on traffic)
   - Idle Timeout: 5 minutes
   - FlashBoot: Enabled (faster cold starts)

## Environment Variables

Set these in RunPod pod configuration:

- `HOST=0.0.0.0` - Bind to all interfaces
- `PORT=8001` - Service port
- `CORS_ORIGINS=https://your-ionos-domain.com` - Allow requests from IONOS server

## Testing

Once deployed, test the service:

```bash
curl https://your-runpod-url/health
```

Should return:
```json
{"status": "healthy", "service": "gpu-processor"}
```

## Security

1. **Use RunPod's built-in authentication** or add API key authentication
2. **Restrict CORS origins** to your IONOS server domain only
3. **Use HTTPS** (RunPod provides this automatically)
4. **Consider adding rate limiting** for production use

## Monitoring

- Monitor GPU usage in RunPod dashboard
- Check logs: RunPod provides log viewing in the pod interface
- Set up alerts for pod failures

## Cost Optimization

- Use **Serverless** for intermittent traffic (pay per request)
- Use **On-Demand Pods** for consistent traffic (pay per hour)
- Consider **Spot Instances** for cost savings (may be interrupted)
- Set up **auto-scaling** based on queue length

