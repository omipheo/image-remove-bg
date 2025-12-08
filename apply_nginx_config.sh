#!/bin/bash
# Simple script to apply nginx configuration

set -e

CONFIG_FILE="/root/image-remove-bg/nginx-image-remove-bg.conf"
NGINX_SITE="/etc/nginx/sites-available/image-remove-bg"
NGINX_ENABLED="/etc/nginx/sites-enabled/image-remove-bg"

echo "=== Applying Nginx Configuration ==="

# Copy config to sites-available
echo "Copying config to $NGINX_SITE..."
sudo cp "$CONFIG_FILE" "$NGINX_SITE"

# Enable the site
if [ ! -L "$NGINX_ENABLED" ]; then
    echo "Enabling site..."
    sudo ln -s "$NGINX_SITE" "$NGINX_ENABLED"
else
    echo "Site already enabled"
fi

# Test configuration
echo ""
echo "Testing nginx configuration..."
if sudo nginx -t; then
    echo "✓ Configuration is valid"
    echo ""
    echo "Reloading nginx..."
    sudo nginx -s reload
    echo "✓ Nginx reloaded successfully"
    echo ""
    echo "WebSocket support is now enabled!"
else
    echo "✗ Configuration has errors"
    exit 1
fi
