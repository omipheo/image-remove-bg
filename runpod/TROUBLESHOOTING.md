# RunPod Troubleshooting Guide

## 502 Bad Gateway Error

If you get a 502 error when accessing your service, it means:
- ✅ Port is exposed correctly (proxy can reach the pod)
- ❌ Service is NOT running on port 8001
- ❌ Service is NOT binding to `0.0.0.0`

### Solution Steps

#### Step 1: Connect to Your Pod

**Option A: Web Terminal**
1. Go to pod → "Connect" tab
2. Enable "Web Terminal"
3. Click "Open Terminal"

**Option B: SSH**
```bash
ssh 5q4c0f92sj6do3-64410ecc@ssh.runpod.io -i ~/.ssh/id_ed25519
```

#### Step 2: Check if Service is Running

```bash
# Check if anything is listening on port 8001
netstat -tulpn | grep 8001
# or
ss -tulpn | grep 8001

# Check if Python process is running
ps aux | grep python
ps aux | grep gpu_processor
```

#### Step 3: Navigate to Your Code

```bash
# Find your code
cd /workspace
ls -la
# or
cd /app
ls -la

# If you cloned the repo
cd /workspace/removebg/backend
# or wherever you put it
```

#### Step 4: Start the Service

```bash
# Make sure you're in the backend directory
cd /workspace/removebg/backend

# Activate virtual environment if you created one
source venv/bin/activate  # if exists

# Install dependencies (if not already done)
pip install -r requirements.txt

# Start the service
python gpu_processor.py
```

**Important**: The service should show:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

#### Step 5: Verify Service is Listening

In another terminal/SSH session, check:

```bash
# Check if port 8001 is listening
netstat -tulpn | grep 8001

# Should show something like:
# tcp  0  0  0.0.0.0:8001  0.0.0.0:*  LISTEN  python
```

#### Step 6: Test Locally on Pod

```bash
# Test from inside the pod
curl http://localhost:8001/health
# or
curl http://127.0.0.1:8001/health

# Should return:
# {"status": "healthy", "service": "gpu-processor"}
```

#### Step 7: Keep Service Running

The service needs to stay running. Options:

**Option A: Run in Background**
```bash
# Run in background
nohup python gpu_processor.py > gpu_service.log 2>&1 &

# Check it's running
ps aux | grep gpu_processor

# View logs
tail -f gpu_service.log
```

**Option B: Use screen/tmux**
```bash
# Install screen
apt-get update && apt-get install -y screen

# Start screen session
screen -S gpu_service

# Run service
python gpu_processor.py

# Detach: Press Ctrl+A, then D
# Reattach: screen -r gpu_service
```

**Option C: Create systemd service (advanced)**
```bash
# Create service file
sudo nano /etc/systemd/system/gpu-processor.service

# Add:
[Unit]
Description=GPU Background Removal Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/workspace/removebg/backend
ExecStart=/usr/bin/python3 /workspace/removebg/backend/gpu_processor.py
Restart=always

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable gpu-processor
sudo systemctl start gpu-processor
sudo systemctl status gpu-processor
```

## Common Issues

### Issue 1: Service Binding to Wrong Address

**Problem**: Service binds to `127.0.0.1` instead of `0.0.0.0`

**Check**:
```bash
netstat -tulpn | grep 8001
# If you see 127.0.0.1:8001, that's wrong
# Should see 0.0.0.0:8001
```

**Fix**: Ensure `gpu_processor.py` has:
```python
host = os.getenv("HOST", "0.0.0.0")  # Not 127.0.0.1!
port = int(os.getenv("PORT", 8001))
uvicorn.run(app, host=host, port=port)
```

### Issue 2: Port Already in Use

**Error**: `Address already in use`

**Solution**:
```bash
# Find what's using port 8001
lsof -i :8001
# or
fuser 8001/tcp

# Kill the process
kill -9 <PID>
```

### Issue 3: Dependencies Not Installed

**Error**: `ModuleNotFoundError`

**Solution**:
```bash
cd /workspace/removebg/backend
pip install -r requirements.txt
```

### Issue 4: GPU Not Available

**Error**: CUDA/GPU related errors

**Solution**:
- Check GPU is available: `nvidia-smi`
- Install GPU-enabled packages:
  ```bash
  pip install onnxruntime-gpu  # Instead of onnxruntime
  ```

### Issue 5: Service Stops After SSH Disconnect

**Solution**: Use `nohup`, `screen`, `tmux`, or systemd service (see Step 7 above)

## Testing Checklist

- [ ] Service is running: `ps aux | grep gpu_processor`
- [ ] Port is listening: `netstat -tulpn | grep 8001`
- [ ] Binding to 0.0.0.0: `netstat` shows `0.0.0.0:8001`
- [ ] Local test works: `curl http://localhost:8001/health`
- [ ] External test works: `curl https://5q4c0f92sj6do3-8001.proxy.runpod.net/health`

## Quick Fix Script

```bash
#!/bin/bash
# Quick start script for GPU service

cd /workspace/removebg/backend || cd /app/backend || exit

# Install dependencies
pip install -r requirements.txt

# Kill any existing service on port 8001
fuser -k 8001/tcp 2>/dev/null

# Start service in background
nohup python gpu_processor.py > gpu_service.log 2>&1 &

# Wait a moment
sleep 2

# Check status
echo "Checking service status..."
ps aux | grep gpu_processor | grep -v grep
netstat -tulpn | grep 8001

# Test
echo "Testing health endpoint..."
curl http://localhost:8001/health

echo "Service should be running. Check logs with: tail -f gpu_service.log"
```

Save as `start_gpu_service.sh`, make executable: `chmod +x start_gpu_service.sh`, then run: `./start_gpu_service.sh`

