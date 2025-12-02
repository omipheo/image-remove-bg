#!/bin/bash

# Deployment script for image-remove-bg
# This script sets up and deploys the application

set -e  # Exit on error

PROJECT_DIR="/root/image-remove-bg"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/venv"
SERVICE_NAME="image-remove-bg-api"
NGINX_SITE="image-remove-bg"

echo "🚀 Starting deployment of image-remove-bg..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root or with sudo"
    exit 1
fi

# Navigate to project directory
cd "$PROJECT_DIR"

# 1. Backend Setup
echo "📦 Setting up backend..."
cd "$BACKEND_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment and install dependencies
echo "Installing backend dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# 2. Frontend Setup
echo "📦 Setting up frontend..."
cd "$FRONTEND_DIR"

# Install frontend dependencies
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

# Build frontend
echo "Building frontend..."
npm run build

# 3. Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p /var/www/image-remove-bg
mkdir -p /var/log/image-remove-bg

# Copy frontend build to web directory
echo "Copying frontend build..."
cp -r "$FRONTEND_DIR/dist"/* /var/www/image-remove-bg/

# Set proper permissions
chown -R www-data:www-data /var/www/image-remove-bg
chown -R www-data:www-data /var/log/image-remove-bg

# 4. Setup systemd service
echo "⚙️  Setting up systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Image Remove Background API Service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$VENV_DIR/bin"
Environment="HOST=127.0.0.1"
Environment="PORT=8000"
ExecStart=$VENV_DIR/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

# 5. Setup nginx configuration
echo "🌐 Setting up nginx configuration..."
if [ -f "/etc/nginx/sites-available/${NGINX_SITE}" ]; then
    echo "Nginx configuration already exists, backing up..."
    cp "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-available/${NGINX_SITE}.backup.$(date +%Y%m%d_%H%M%S)"
fi

# Check if nginx.conf.example exists, use it, otherwise create default
if [ -f "$PROJECT_DIR/nginx.conf.example" ]; then
    cp "$PROJECT_DIR/nginx.conf.example" "/etc/nginx/sites-available/${NGINX_SITE}"
else
    # Create default nginx config
    cat > "/etc/nginx/sites-available/${NGINX_SITE}" <<'NGINX_EOF'
server {
    listen 80;
    server_name _;

    # Frontend
    root /var/www/image-remove-bg;
    index index.html;

    # Frontend routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }

    # Health check
    location /api/health {
        proxy_pass http://127.0.0.1:8000/api/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # Static files caching
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
NGINX_EOF
fi

# Enable nginx site
if [ ! -L "/etc/nginx/sites-enabled/${NGINX_SITE}" ]; then
    ln -s "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-enabled/${NGINX_SITE}"
fi

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

# 6. Restart services
echo "🔄 Restarting services..."
systemctl restart ${SERVICE_NAME}
systemctl restart nginx

# 7. Check service status
echo "✅ Checking service status..."
sleep 2
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo "✅ Backend service is running"
else
    echo "❌ Backend service failed to start. Check logs with: journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi

if systemctl is-active --quiet nginx; then
    echo "✅ Nginx is running"
else
    echo "❌ Nginx failed to start. Check logs with: journalctl -u nginx -n 50"
    exit 1
fi

echo ""
echo "🎉 Deployment completed successfully!"
echo ""
echo "📋 Service Information:"
echo "   - Backend API: http://127.0.0.1:8000"
echo "   - Frontend: http://$(hostname -I | awk '{print $1}')"
echo ""
echo "📝 Useful commands:"
echo "   - Check backend logs: journalctl -u ${SERVICE_NAME} -f"
echo "   - Check nginx logs: tail -f /var/log/nginx/error.log"
echo "   - Restart backend: systemctl restart ${SERVICE_NAME}"
echo "   - Restart nginx: systemctl restart nginx"
echo ""

