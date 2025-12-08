#!/bin/bash
# Script to update nginx configuration for WebSocket support

set -e

echo "=== Finding and Updating Nginx Configuration ==="

# Find nginx config files
NGINX_CONF=""
CONFIG_FOUND=false

# Check common locations
if [ -f "/etc/nginx/sites-available/image-remove-bg" ]; then
    NGINX_CONF="/etc/nginx/sites-available/image-remove-bg"
    CONFIG_FOUND=true
elif [ -f "/etc/nginx/conf.d/image-remove-bg.conf" ]; then
    NGINX_CONF="/etc/nginx/conf.d/image-remove-bg.conf"
    CONFIG_FOUND=true
elif [ -f "/etc/nginx/sites-available/default" ]; then
    # Check if it's already configured for image-remove-bg
    if grep -q "image-remove-bg\|/var/www/image-remove-bg" /etc/nginx/sites-available/default 2>/dev/null; then
        NGINX_CONF="/etc/nginx/sites-available/default"
        CONFIG_FOUND=true
    fi
fi

# If not found, check all config files for port 36446 or image-remove-bg references
if [ "$CONFIG_FOUND" = false ]; then
    echo "Searching for nginx config with port 36446 or image-remove-bg references..."
    for conf in /etc/nginx/sites-available/* /etc/nginx/conf.d/*.conf 2>/dev/null; do
        if [ -f "$conf" ] && (grep -q "36446\|image-remove-bg\|/var/www/image-remove-bg" "$conf" 2>/dev/null); then
            NGINX_CONF="$conf"
            CONFIG_FOUND=true
            break
        fi
    done
fi

# If still not found, create a new config
if [ "$CONFIG_FOUND" = false ]; then
    echo "No existing config found. Creating new config..."
    NGINX_CONF="/etc/nginx/sites-available/image-remove-bg"
    
    # Create config from example
    if [ -f "/root/image-remove-bg/nginx.conf.example" ]; then
        sudo cp /root/image-remove-bg/nginx.conf.example "$NGINX_CONF"
        echo "Created config from example: $NGINX_CONF"
    else
        echo "Error: nginx.conf.example not found"
        exit 1
    fi
fi

echo "Using nginx config: $NGINX_CONF"

# Check if WebSocket location already exists
if grep -q "location /ws/" "$NGINX_CONF"; then
    echo "✓ WebSocket location already exists in nginx config"
    echo "Verifying configuration..."
    
    # Check if it has the required headers
    if grep -q "Upgrade.*http_upgrade" "$NGINX_CONF" && grep -q "Connection.*upgrade" "$NGINX_CONF"; then
        echo "✓ WebSocket configuration looks correct"
    else
        echo "⚠ WebSocket location exists but may be missing required headers"
    fi
else
    echo "Adding WebSocket location block..."
    
    # Create backup
    sudo cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Backup created: ${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Read the file
    CONFIG_CONTENT=$(cat "$NGINX_CONF")
    
    # Check if /api location exists
    if echo "$CONFIG_CONTENT" | grep -q "location /api"; then
        # Insert WebSocket location before /api
        WS_BLOCK="# WebSocket proxy for pipelined processing
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
        
        # WebSocket timeouts (longer for batch processing)
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }
"
        
        # Use sed to insert before /api location
        echo "$CONFIG_CONTENT" | sudo tee "$NGINX_CONF.tmp" > /dev/null
        sudo sed -i "/location \/api/i\\$WS_BLOCK" "$NGINX_CONF.tmp"
        sudo mv "$NGINX_CONF.tmp" "$NGINX_CONF"
        echo "✓ WebSocket location block added"
    else
        echo "⚠ Could not find /api location block. Please manually add WebSocket configuration."
        echo ""
        echo "Add this block to your nginx config:"
        echo "$WS_BLOCK"
        exit 1
    fi
fi

# Enable the site if it's in sites-available
if [[ "$NGINX_CONF" == *"sites-available"* ]]; then
    SITE_NAME=$(basename "$NGINX_CONF")
    if [ ! -L "/etc/nginx/sites-enabled/$SITE_NAME" ]; then
        echo "Enabling site: $SITE_NAME"
        sudo ln -s "$NGINX_CONF" "/etc/nginx/sites-enabled/$SITE_NAME"
    fi
fi

# Test nginx config
echo ""
echo "Testing nginx configuration..."
if sudo nginx -t; then
    echo "✓ Nginx configuration is valid"
    echo ""
    echo "To apply changes, run:"
    echo "  sudo nginx -s reload"
    echo ""
    read -p "Reload nginx now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo nginx -s reload
        echo "✓ Nginx reloaded successfully"
    else
        echo "Please reload nginx manually: sudo nginx -s reload"
    fi
else
    echo "✗ Nginx configuration has errors - please fix them before reloading"
    exit 1
fi

echo ""
echo "=== Done ==="
