#!/bin/bash

# Deployment script for image-remove-bg using PM2
# This script sets up and deploys the application without requiring systemd

set -e  # Exit on error

PROJECT_DIR="/root/image-remove-bg"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/venv"
NGINX_SITE="image-remove-bg"

echo "🚀 Starting deployment of image-remove-bg with PM2..."

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

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << EOF
HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=
WORKERS=1
EOF
fi

# Create PM2 ecosystem config
echo "Creating PM2 configuration..."
cat > ecosystem.config.js << 'EOF'
module.exports = {
  apps: [{
    name: 'image-remove-bg-api',
    script: 'main.py',
    interpreter: '/root/image-remove-bg/backend/venv/bin/python',
    cwd: '/root/image-remove-bg/backend',
    instances: 1,
    exec_mode: 'fork',
    env: {
      HOST: '127.0.0.1',
      PORT: '8000',
      CORS_ORIGINS: '',
      WORKERS: '1'
    },
    error_file: '/var/log/image-remove-bg/error.log',
    out_file: '/var/log/image-remove-bg/out.log',
    log_file: '/var/log/image-remove-bg/combined.log',
    time: true,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    merge_logs: true,
    kill_timeout: 10000,
    wait_ready: true,
    listen_timeout: 10000,
    shutdown_with_message: true
  }]
};
EOF

# Create log directory
mkdir -p /var/log/image-remove-bg
chmod 755 /var/log/image-remove-bg

# Install PM2 if not installed
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    npm install -g pm2
fi

# Stop existing PM2 process if running
pm2 delete image-remove-bg-api 2>/dev/null || true

# Start with PM2
echo "Starting backend with PM2..."
pm2 start ecosystem.config.js
pm2 save

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
chown -R www-data:www-data /var/www/image-remove-bg 2>/dev/null || chown -R root:root /var/www/image-remove-bg
chown -R www-data:www-data /var/log/image-remove-bg 2>/dev/null || chown -R root:root /var/log/image-remove-bg

# 4. Setup nginx configuration
echo "🌐 Setting up nginx configuration..."
if [ -f "/etc/nginx/sites-available/${NGINX_SITE}" ]; then
    echo "Nginx configuration already exists, backing up..."
    cp "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-available/${NGINX_SITE}.backup.$(date +%Y%m%d_%H%M%S)"
fi

# Use nginx.conf.example if it exists
if [ -f "$PROJECT_DIR/nginx.conf.example" ]; then
    cp "$PROJECT_DIR/nginx.conf.example" "/etc/nginx/sites-available/${NGINX_SITE}"
else
    # Create default nginx config
    cat > "/etc/nginx/sites-available/${NGINX_SITE}" <<'NGINX_EOF'
server {
    listen 80;
    server_name _;

    root /var/www/image-remove-bg;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

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
        proxy_send_timeout 300s;
        client_max_body_size 50M;
    }

    location /api/health {
        proxy_pass http://127.0.0.1:8000/api/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        access_log off;
    }

    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/json;
}
NGINX_EOF
fi

# Enable nginx site
if [ ! -L "/etc/nginx/sites-enabled/${NGINX_SITE}" ]; then
    ln -sf "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-enabled/${NGINX_SITE}"
fi
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

# Start/restart nginx
echo "Starting nginx..."
nginx -s reload 2>/dev/null || nginx -g "daemon off;" & 2>/dev/null || systemctl restart nginx 2>/dev/null || true

# 5. Check service status
echo "✅ Checking service status..."
sleep 3

if pm2 list | grep -q "image-remove-bg-api.*online"; then
    echo "✅ Backend service is running (PM2)"
else
    echo "⚠️  Backend service status unclear. Check with: pm2 status"
fi

if ps aux | grep -q "[n]ginx: master"; then
    echo "✅ Nginx is running"
else
    echo "⚠️  Nginx status unclear. Check with: ps aux | grep nginx"
fi

echo ""
echo "🎉 Deployment completed!"
echo ""
echo "📋 Service Information:"
echo "   - Backend API: http://127.0.0.1:8000"
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')
echo "   - Server IP: $PUBLIC_IP"
echo ""
echo "📝 Useful commands:"
echo "   - PM2 status: pm2 status"
echo "   - PM2 logs: pm2 logs image-remove-bg-api"
echo "   - Restart backend: pm2 restart image-remove-bg-api"
echo "   - Nginx reload: nginx -s reload"
echo "   - Check nginx: nginx -t"
echo ""
echo "🌐 Access:"
echo "   - SSH port forwarding: ssh -L 8080:localhost:80 root@$PUBLIC_IP"
echo "   - Then open: http://localhost:8080"
echo ""

