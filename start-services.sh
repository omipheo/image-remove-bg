#!/bin/bash
# Auto-start script for Image Remove BG Services
# This script starts PM2 backend and Nginx frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/image-remove-bg/startup.log"

# Create log directory if it doesn't exist
mkdir -p /var/log/image-remove-bg

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Starting Image Remove BG Services ==="

# 1. Start backend with PM2
log "1. Starting backend with PM2..."
cd /root/image-remove-bg/backend

# Check if PM2 process exists
if pm2 describe image-remove-bg-api > /dev/null 2>&1; then
    log "   Backend already running, restarting..."
    pm2 restart image-remove-bg-api
else
    log "   Starting new backend process..."
    pm2 start ecosystem.config.js
fi

# Save PM2 process list
pm2 save

# Wait for backend to be ready
sleep 3

# 2. Start nginx
log "2. Starting nginx..."

# Check if nginx is already running
if pgrep -x nginx > /dev/null; then
    log "   Nginx already running, reloading config..."
    nginx -t && nginx -s reload || log "   Warning: Nginx reload failed"
else
    log "   Starting nginx..."
    nginx -t && nginx || log "   Error: Failed to start nginx"
fi

# Wait for services to stabilize
sleep 2

# 3. Verify services
log "3. Verifying services..."

BACKEND_STATUS=$(curl -s http://127.0.0.1:8000/api/health 2>/dev/null || echo "failed")
FRONTEND_HTTP=$(curl -s -I http://127.0.0.1/ 2>/dev/null | head -1 || echo "failed")
FRONTEND_HTTPS=$(curl -s -k -I https://127.0.0.1/ 2>/dev/null | head -1 || echo "failed")

if [[ "$BACKEND_STATUS" == *"healthy"* ]]; then
    log "✅ Backend: Running on port 8000"
else
    log "❌ Backend: Not responding"
fi

if [[ "$FRONTEND_HTTP" == *"200"* ]] || [[ "$FRONTEND_HTTP" == *"301"* ]] || [[ "$FRONTEND_HTTP" == *"302"* ]]; then
    log "✅ Frontend HTTP: Running on port 80"
else
    log "❌ Frontend HTTP: Not responding"
fi

if [[ "$FRONTEND_HTTPS" == *"200"* ]]; then
    log "✅ Frontend HTTPS: Running on port 443"
else
    log "❌ Frontend HTTPS: Not responding"
fi

# Check port listeners
log ""
log "4. Port Status:"
if ss -tlnp 2>/dev/null | grep -q ':80 '; then
    log "   ✅ Port 80: Listening"
else
    log "   ❌ Port 80: Not listening"
fi

if ss -tlnp 2>/dev/null | grep -q ':443 '; then
    log "   ✅ Port 443: Listening"
else
    log "   ❌ Port 443: Not listening"
fi

if ss -tlnp 2>/dev/null | grep -q ':8000 '; then
    log "   ✅ Port 8000: Listening"
else
    log "   ❌ Port 8000: Not listening"
fi

log ""
log "=== PM2 Status ==="
pm2 list | tee -a "$LOG_FILE"

log ""
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "161.184.141.187")
log "🌐 Access your application at:"
log "   HTTP:  http://$PUBLIC_IP:43752"
log "   HTTPS: https://$PUBLIC_IP:43930"
log ""
log "=== Services Started Successfully ==="

