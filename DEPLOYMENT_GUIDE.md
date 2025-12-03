# Image Remove Background - Deployment Guide

Complete guide to deploy the image-remove-bg application on a Linux server.

## Prerequisites

- Python 3.12+
- Node.js 18+
- npm
- Nginx
- PM2 (for process management)

## Quick Deployment

### Step 1: Install Prerequisites

```bash
# Update system
sudo apt-get update

# Install Node.js and npm
sudo apt-get install -y nodejs npm

# Install Nginx
sudo apt-get install -y nginx

# Install PM2 globally
sudo npm install -g pm2
```

### Step 2: Clone and Navigate to Project

```bash
cd /root
git clone https://github.com/omipheo/image-remove-bg.git
cd image-remove-bg
```

### Step 3: Deploy Backend

```bash
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
HOST=127.0.0.1
PORT=8000
CORS_ORIGINS=
WORKERS=1
EOF

# Create PM2 ecosystem config
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
sudo mkdir -p /var/log/image-remove-bg
sudo chmod 755 /var/log/image-remove-bg

# Start with PM2
pm2 start ecosystem.config.js
pm2 save
```

### Step 4: Deploy Frontend

```bash
cd ../frontend

# Install dependencies
npm install

# Build for production
npm run build

# Deploy to web directory
sudo mkdir -p /var/www/image-remove-bg
sudo cp -r dist/* /var/www/image-remove-bg/
sudo chown -R www-data:www-data /var/www/image-remove-bg
```

### Step 5: Configure Nginx

```bash
# Copy nginx configuration
sudo cp /root/image-remove-bg/nginx.conf.example /etc/nginx/sites-available/image-remove-bg

# Enable site
sudo ln -sf /etc/nginx/sites-available/image-remove-bg /etc/nginx/sites-enabled/image-remove-bg
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload nginx
sudo nginx -s reload
```

### Step 6: Verify Deployment

```bash
# Check backend
curl http://127.0.0.1:8000/api/health

# Check frontend
curl http://127.0.0.1/

# Check PM2 status
pm2 status

# Check nginx
sudo systemctl status nginx
```

## Access the Application

### For Vast.ai or Docker Containers

Use SSH port forwarding:

```bash
# On your local machine
ssh -L 8080:localhost:80 root@YOUR_SERVER_IP

# Then open in browser
http://localhost:8080
```

### For Direct Access

If port 80 is accessible:

```bash
# Open in browser
http://YOUR_SERVER_IP
```

## Management Commands

### Backend (PM2)

```bash
# View status
pm2 status

# View logs
pm2 logs image-remove-bg-api

# Restart
pm2 restart image-remove-bg-api

# Stop
pm2 stop image-remove-bg-api

# Monitor
pm2 monit
```

### Nginx

```bash
# Restart
sudo systemctl restart nginx

# Reload config
sudo nginx -s reload

# Check status
sudo systemctl status nginx

# View logs
sudo tail -f /var/log/nginx/error.log
```

## Troubleshooting

### Backend not starting
```bash
# Check PM2 logs
pm2 logs image-remove-bg-api --lines 50

# Check if port 8000 is in use
ss -tlnp | grep 8000
```

### Nginx 502 Bad Gateway
```bash
# Check if backend is running
pm2 status

# Check backend logs
pm2 logs image-remove-bg-api

# Test backend directly
curl http://127.0.0.1:8000/api/health
```

### Frontend not loading
```bash
# Check if files exist
ls -la /var/www/image-remove-bg/

# Rebuild frontend
cd /root/image-remove-bg/frontend
npm run build
sudo cp -r dist/* /var/www/image-remove-bg/
```

## File Locations

- Backend: `/root/image-remove-bg/backend`
- Frontend: `/root/image-remove-bg/frontend`
- Frontend Build: `/var/www/image-remove-bg`
- Nginx Config: `/etc/nginx/sites-available/image-remove-bg`
- PM2 Config: `/root/image-remove-bg/backend/ecosystem.config.js`
- Logs: `/var/log/image-remove-bg/`

