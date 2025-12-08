#!/bin/bash
# Test and reload nginx configuration

echo "=== Testing Nginx Configuration ==="
if sudo nginx -t; then
    echo ""
    echo "✓ Configuration is valid"
    echo ""
    echo "Reloading nginx..."
    sudo nginx -s reload
    echo "✓ Nginx reloaded successfully"
    echo ""
    echo "WebSocket support is now enabled!"
else
    echo "✗ Configuration has errors - please fix them"
    exit 1
fi
