#!/bin/bash
# Script to update nginx configuration for WebSocket support

echo "=== Updating Nginx Configuration for WebSocket ==="

# Find nginx config file
NGINX_CONF=""
if [ -f "/etc/nginx/sites-available/default" ]; then
    NGINX_CONF="/etc/nginx/sites-available/default"
elif [ -f "/etc/nginx/nginx.conf" ]; then
    NGINX_CONF="/etc/nginx/nginx.conf"
else
    echo "Error: Could not find nginx configuration file"
    echo "Please manually update your nginx config to include WebSocket proxy"
    exit 1
fi

echo "Found nginx config: $NGINX_CONF"

# Check if WebSocket location already exists
if grep -q "location /ws/" "$NGINX_CONF"; then
    echo "WebSocket location already exists in nginx config"
else
    echo "Adding WebSocket location block..."
    
    # Create backup
    cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Add WebSocket location before /api location
    # This is a simple approach - you may need to adjust based on your config structure
    echo ""
    echo "Please manually add this to your nginx config file ($NGINX_CONF) BEFORE the /api location block:"
    echo ""
    echo "    # WebSocket proxy for pipelined processing"
    echo "    location /ws/ {"
    echo "        proxy_pass http://127.0.0.1:8000;"
    echo "        proxy_http_version 1.1;"
    echo "        proxy_set_header Upgrade \$http_upgrade;"
    echo "        proxy_set_header Connection \"upgrade\";"
    echo "        proxy_set_header Host \$host;"
    echo "        proxy_set_header X-Real-IP \$remote_addr;"
    echo "        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    echo "        proxy_set_header X-Forwarded-Proto \$scheme;"
    echo "        proxy_cache_bypass \$http_upgrade;"
    echo "        proxy_read_timeout 600s;"
    echo "        proxy_connect_timeout 600s;"
    echo "        proxy_send_timeout 600s;"
    echo "    }"
    echo ""
fi

# Test nginx config
echo "Testing nginx configuration..."
if sudo nginx -t; then
    echo "✓ Nginx configuration is valid"
    echo ""
    echo "To apply changes, run:"
    echo "  sudo nginx -s reload"
else
    echo "✗ Nginx configuration has errors - please fix them before reloading"
    exit 1
fi
