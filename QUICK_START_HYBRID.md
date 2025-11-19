# Quick Start: IONOS + RunPod Hybrid Deployment

This is a condensed guide to get you up and running quickly. For detailed information, see [HYBRID_DEPLOYMENT.md](./HYBRID_DEPLOYMENT.md).

## Cost Summary

- **RunPod RTX A4000**: 
  - Serverless: ~$0.40/hour when active (pay per use)
  - On-Demand: ~$0.17/hour (~$122/month if 24/7)
  - **Recommended**: Start with Serverless, switch to On-Demand if using >8 hours/day

- **IONOS Server**: Your existing server (no additional cost)

- **Total**: ~$11-140/month depending on traffic

## 5-Minute Setup

### Step 1: Deploy GPU Service on RunPod (3 minutes)

1. **Create RunPod Account**
   - Go to [runpod.io](https://www.runpod.io)
   - Sign up and add $10-50 credits

2. **Deploy Pod**
   - Click "Pods" → "Deploy Pod"
   - Select: **RTX A4000** GPU
   - Template: **RunPod PyTorch 2.1.0**
   - Port: **8001** (expose publicly)
   - Click "Deploy"

3. **Expose Port 8001**
   - Go to your pod's **"Details"** tab (not "Connect")
   - Look for **"Expose HTTP Ports"** or **"HTTP Ports"** field
   - Add port **8001** to the list
   - **Save** the changes (this will restart your pod)
   - Wait for pod to restart (2-3 minutes)

4. **Get Public URL**
   - After pod restarts, the HTTP proxy URL format is:
     ```
     https://[POD_ID]-[PORT].proxy.runpod.net
     ```
   - For your pod ID `5q4c0f92sj6do3` and port `8001`:
     ```
     https://5q4c0f92sj6do3-8001.proxy.runpod.net
     ```
   - You can also check the **"Connect"** tab → **"HTTP Services"** section to see the URL
   - ⚠️ **Note**: The "Direct TCP Ports" section is for SSH, NOT the HTTP URL you need!

5. **Deploy Code** (via web terminal or SSH)
   ```bash
   # Connect to pod (Web Terminal or SSH)
   cd /workspace
   git clone <your-repo-url> removebg
   cd removebg/backend
   pip install -r requirements.txt
   
   # Start service (must bind to 0.0.0.0, not 127.0.0.1)
   python gpu_processor.py
   ```
   
   **Important**: 
   - Service must run continuously (use `nohup`, `screen`, or systemd)
   - Service must bind to `0.0.0.0` (already configured in `gpu_processor.py`)
   - Keep the terminal/session open, or run in background

6. **Test the Service**
   ```bash
   # From inside the pod
   curl http://localhost:8001/health
   
   # From outside (your computer)
   curl https://5q4c0f92sj6do3-8001.proxy.runpod.net/health
   ```
   
   If you get **502 error**, see [TROUBLESHOOTING.md](./runpod/TROUBLESHOOTING.md) - service is not running!

### Step 2: Configure IONOS Server (2 minutes)

1. **SSH into IONOS server**
   ```bash
   ssh user@your-ionos-server
   ```

2. **Create/Update `.env` file**
   ```bash
   cd /var/www/removebg/backend
   nano .env
   ```
   
   Add:
   ```env
   USE_REMOTE_GPU=true
   GPU_SERVICE_URL=https://xxxxx-8001.proxy.runpod.net
   ```

3. **Restart service**
   ```bash
   sudo systemctl restart removebg-backend
   ```

4. **Verify**
   ```bash
   curl http://localhost:8000/api/health
   ```
   
   Should show:
   ```json
   {
     "status": "healthy",
     "mode": "remote-gpu",
     "gpu_service_status": "healthy"
   }
   ```

## Done! 🎉

Your application is now using GPU acceleration. Test it by uploading an image through your frontend.

## Troubleshooting

**GPU service not responding?**
- Check RunPod pod is running
- Verify URL is correct: `curl https://your-runpod-url/health`
- Check CORS settings in RunPod pod environment

**IONOS can't connect?**
- Verify `.env` file has correct `GPU_SERVICE_URL`
- Test connection: `curl https://your-runpod-url/health`
- Check logs: `sudo journalctl -u removebg-backend -n 50`

## Next Steps

- See [HYBRID_DEPLOYMENT.md](./HYBRID_DEPLOYMENT.md) for detailed configuration
- See [CONFIGURATION.md](./CONFIGURATION.md) for all environment variables
- Monitor costs in RunPod dashboard
- Consider Serverless for cost savings on low traffic

