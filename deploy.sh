#!/bin/bash

# Deployment script for IONOS server
set -e

echo "Starting deployment..."

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || exit

# Backend setup
echo "Setting up backend..."
cd backend || exit

# Check Python version and use python3.12 if available, otherwise python3
PYTHON_CMD="python3"
if command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
    echo "Using Python 3.12"
elif command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
    echo "Using Python 3.11"
else
    echo "Using default Python 3 (may need Python 3.11+ for scipy 1.16.3)"
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create systemd service file if it doesn't exist
if [ ! -f "/etc/systemd/system/removebg-backend.service" ]; then
    sudo tee /etc/systemd/system/removebg-backend.service > /dev/null <<EOF
[Unit]
Description=RemoveBG Backend API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/removebg/backend
Environment="PATH=/var/www/removebg/backend/venv/bin"
ExecStart=/var/www/removebg/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable removebg-backend.service
fi

# Restart backend service
sudo systemctl restart removebg-backend.service

# Frontend setup (if using nginx)
echo "Setting up frontend..."
cd ../frontend/dist || exit

# Copy frontend files to nginx directory (adjust path as needed)
if [ -d "/var/www/html/removebg" ]; then
    sudo cp -r * /var/www/html/removebg/
else
    sudo mkdir -p /var/www/html/removebg
    sudo cp -r * /var/www/html/removebg/
fi

# Set permissions
sudo chown -R www-data:www-data /var/www/html/removebg
sudo chown -R www-data:www-data /var/www/removebg/backend

echo "Deployment completed successfully!"
echo "Backend service status:"
sudo systemctl status removebg-backend.service --no-pager -l

