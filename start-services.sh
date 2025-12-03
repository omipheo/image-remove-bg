#!/bin/bash
# Quick script to start all services after instance restart

set -e

echo "=== Starting Image Remove BG Services ==="
echo ""

# Start backend with PM2
echo "1. Starting backend..."
cd /root/image-remove-bg/backend
pm2 start ecosystem.config.js || pm2 restart ecosystem.config.js
pm2 save

# Start nginx
echo "2. Starting nginx..."
nginx -t && nginx || echo "Nginx already running or error"

# Wait a moment
sleep 2

# Verify services
echo ""
echo "3. Verifying services..."
echo ""

BACKEND_STATUS=$(curl -s http://127.0.0.1:8000/api/health 2>/dev/null || echo "failed")
FRONTEND_STATUS=$(curl -s -I http://127.0.0.1/ 2>/dev/null | head -1 || echo "failed")

if [[ "$BACKEND_STATUS" == *"healthy"* ]]; then
    echo "✅ Backend: Running"
else
    echo "❌ Backend: Not responding"
fi

if [[ "$FRONTEND_STATUS" == *"200"* ]]; then
    echo "✅ Frontend: Running"
else
    echo "❌ Frontend: Not responding"
fi

echo ""
echo "=== Services Status ==="
pm2 list

echo ""
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "161.184.141.187")
echo "🌐 Access your application at:"
echo "   HTTPS: https://$PUBLIC_IP"
echo "   HTTP:  http://$PUBLIC_IP (redirects to HTTPS)"
echo ""

