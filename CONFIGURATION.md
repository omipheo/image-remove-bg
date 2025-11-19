# Configuration Guide

This guide explains how to configure the hybrid IONOS + RunPod deployment.

## Environment Variables

### IONOS Server Configuration

Create `/var/www/removebg/backend/.env` on your IONOS server:

```env
# Server Configuration
HOST=0.0.0.0
PORT=8000

# CORS Configuration
# Comma-separated list of allowed origins
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,https://your-domain.com

# GPU Processing Configuration
# Set to true to use remote RunPod GPU service
USE_REMOTE_GPU=true

# RunPod GPU Service URL
# Format: https://xxxxx-8001.proxy.runpod.net
# Or direct IP: http://runpod-ip:8001
GPU_SERVICE_URL=https://xxxxx-8001.proxy.runpod.net
```

### RunPod GPU Service Configuration

Set these in RunPod pod environment variables (via RunPod dashboard):

```env
# Server Configuration
HOST=0.0.0.0
PORT=8001

# CORS Configuration
# Allow requests from IONOS server
# Format: https://your-ionos-domain.com,https://your-ionos-ip
# Use * for testing only (not recommended for production)
CORS_ORIGINS=https://your-ionos-domain.com

# Optional: API Key for authentication
API_KEY=your-secret-api-key
```

## Configuration Modes

### Mode 1: Remote GPU (Hybrid Architecture)

**IONOS Server:**
```env
USE_REMOTE_GPU=true
GPU_SERVICE_URL=https://your-runpod-url
```

**RunPod:**
- Deploy `gpu_processor.py`
- Expose port 8001
- Set CORS_ORIGINS to IONOS domain

**Use Case:** Production with GPU acceleration

### Mode 2: Local CPU (Standalone)

**IONOS Server:**
```env
USE_REMOTE_GPU=false
```

**RunPod:**
- Not needed

**Use Case:** Development, testing, or low-cost deployment

## Frontend Configuration

### Development

Create `frontend/.env.local`:
```env
VITE_API_BASE_URL=http://localhost:8000
```

### Production

Set in GitHub Secrets (for CI/CD) or `frontend/.env.production`:
```env
VITE_API_BASE_URL=https://your-ionos-domain.com
```

## Verifying Configuration

### Check IONOS API Gateway

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "mode": "remote-gpu",
  "gpu_service_status": "healthy"
}
```

### Check RunPod GPU Service

```bash
curl https://your-runpod-url/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "gpu-processor"
}
```

## Switching Between Modes

### Enable Remote GPU

1. Update IONOS `.env`:
   ```bash
   echo "USE_REMOTE_GPU=true" >> /var/www/removebg/backend/.env
   echo "GPU_SERVICE_URL=https://your-runpod-url" >> /var/www/removebg/backend/.env
   ```

2. Restart service:
   ```bash
   sudo systemctl restart removebg-backend
   ```

3. Verify:
   ```bash
   curl http://localhost:8000/api/health
   ```

### Disable Remote GPU (Use Local CPU)

1. Update IONOS `.env`:
   ```bash
   echo "USE_REMOTE_GPU=false" >> /var/www/removebg/backend/.env
   ```

2. Restart service:
   ```bash
   sudo systemctl restart removebg-backend
   ```

3. Verify:
   ```bash
   curl http://localhost:8000/api/health
   ```

## Security Best Practices

1. **CORS Configuration:**
   - Never use `*` in production
   - Only allow your specific domains
   - Use HTTPS URLs

2. **API Keys (Optional):**
   - Add API key authentication to RunPod service
   - Pass API key in requests from IONOS

3. **HTTPS:**
   - Use HTTPS for all production endpoints
   - RunPod provides HTTPS automatically via proxy
   - Configure SSL on IONOS server

4. **Environment Variables:**
   - Don't commit `.env` files to Git
   - Use secure storage for secrets
   - Rotate keys regularly

## Troubleshooting

### GPU Service Unreachable

1. Check RunPod pod is running
2. Verify `GPU_SERVICE_URL` is correct
3. Test connection:
   ```bash
   curl https://your-runpod-url/health
   ```
4. Check CORS settings

### Wrong Mode Detected

1. Check `.env` file:
   ```bash
   cat /var/www/removebg/backend/.env
   ```
2. Verify environment variables are loaded:
   ```bash
   sudo systemctl status removebg-backend
   ```
3. Restart service:
   ```bash
   sudo systemctl restart removebg-backend
   ```

