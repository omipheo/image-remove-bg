# Deployment Guide for IONOS Server

This guide explains how to deploy the Background Removal Tool to an IONOS server using CI/CD pipeline.

## Prerequisites

1. IONOS server with SSH access
2. Python 3.12+ installed
3. Node.js 18+ installed (for building frontend)
4. Nginx installed (for serving frontend and proxying API)
5. GitHub repository with Actions enabled

## Setup Instructions

### 1. Server Preparation

#### Install Required Software

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install python3 python3-pip python3-venv -y

# Install Node.js (if not already installed)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install Nginx
sudo apt install nginx -y

# Install Git
sudo apt install git -y
```

#### Create Deployment Directory

```bash
sudo mkdir -p /var/www/removebg
sudo chown -R $USER:$USER /var/www/removebg
```

### 2. GitHub Secrets Configuration

Go to your GitHub repository → Settings → Secrets and variables → Actions, and ensure you have the following secrets:

**Required Secrets:**
- `SERVER_HOST`: Your IONOS server IP address or domain
- `SERVER_USER`: SSH username (usually `root` or your user)
- `IONOS_SSH_KEY`: Your private SSH key (content of `~/.ssh/id_rsa`) - **MUST BE ADDED**
- `REMOVE_BG_HOST`: Your production API URL (e.g., `https://yourdomain.com` or `http://your-ip:8000`)

**Optional Secrets:**
- `DEPLOY_PATH`: Deployment directory path (default: `/var/www/removebg`)
- `SSH_BACKEND_PORT`: SSH port for backend deployment (default: 22)
- `SSH_FRONTEND_PORT`: SSH port for frontend deployment (default: 22)

#### Generate SSH Key (if needed)

```bash
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
# Copy public key to server
ssh-copy-id username@your-server-ip
```

### 3. Nginx Configuration

1. Copy the example nginx config:
```bash
sudo cp nginx.conf.example /etc/nginx/sites-available/removebg
```

2. Edit the configuration:
```bash
sudo nano /etc/nginx/sites-available/removebg
```

3. Update `server_name` with your domain or IP

4. Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/removebg /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl reload nginx
```

### 4. Firewall Configuration

```bash
# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow SSH (if not already allowed)
sudo ufw allow 22/tcp

# If running backend on port 8000 directly (not recommended)
sudo ufw allow 8000/tcp
```

### 5. CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/deploy.yml`) will automatically:

1. Build the frontend React app
2. Install backend Python dependencies
3. Deploy files to the server via SCP
4. Execute the deployment script on the server

### 6. Manual Deployment (Alternative)

If you prefer manual deployment:

```bash
# On your local machine
cd frontend
npm install
npm run build

# Copy files to server
scp -r frontend/dist/* username@server:/var/www/html/removebg/
scp -r backend/* username@server:/var/www/removebg/backend/

# SSH into server
ssh username@server

# Run deployment script
cd /var/www/removebg
chmod +x deploy.sh
./deploy.sh
```

## Environment Variables

### Backend

Create a `.env` file in the backend directory (optional):

```bash
# /var/www/removebg/backend/.env
PORT=8000
HOST=0.0.0.0
```

### Frontend

The frontend uses `VITE_API_BASE_URL` environment variable. Set it in GitHub Actions secrets or create a `.env.production` file:

```bash
# frontend/.env.production
VITE_API_BASE_URL=https://yourdomain.com
```

## Service Management

### Backend Service

```bash
# Check status
sudo systemctl status removebg-backend

# Start service
sudo systemctl start removebg-backend

# Stop service
sudo systemctl stop removebg-backend

# Restart service
sudo systemctl restart removebg-backend

# View logs
sudo journalctl -u removebg-backend -f
```

### Nginx Service

```bash
# Check status
sudo systemctl status nginx

# Reload configuration
sudo systemctl reload nginx

# Restart
sudo systemctl restart nginx
```

## Troubleshooting

### SSH Connection Timeout (GitHub Actions can't connect)

If you see `dial tcp ***:***: i/o timeout` error, check the following on your server:

1. **Check SSH service status:**
   ```bash
   sudo systemctl status ssh
   # or
   sudo systemctl status sshd
   ```

2. **Check what port SSH is listening on:**
   ```bash
   sudo ss -tlnp | grep ssh
   # or
   sudo netstat -tlnp | grep ssh
   ```
   Make sure the port matches your `SSH_BACKEND_PORT` secret (default is 22).

3. **Check firewall (UFW) status:**
   ```bash
   sudo ufw status
   # If SSH port is blocked, allow it:
   sudo ufw allow 22/tcp
   # or if using custom port:
   sudo ufw allow YOUR_SSH_PORT/tcp
   sudo ufw reload
   ```

4. **Check IONOS Firewall/Security Groups:**
   - Log into IONOS control panel
   - Go to your server's firewall/security settings
   - Ensure SSH port (usually 22) is open for incoming connections
   - Allow connections from `0.0.0.0/0` or GitHub Actions IP ranges

5. **Verify SSH is accessible from outside:**
   ```bash
   # On your local machine, test connection:
   ssh -v -p YOUR_PORT username@YOUR_SERVER_IP
   ```

6. **Check SSH configuration:**
   ```bash
   sudo nano /etc/ssh/sshd_config
   # Ensure these are set:
   # Port 22 (or your custom port)
   # PermitRootLogin yes (if using root)
   # PasswordAuthentication no (if using keys only)
   # Then restart SSH:
   sudo systemctl restart ssh
   ```

7. **Verify public key is in authorized_keys:**
   ```bash
   cat ~/.ssh/authorized_keys
   # Make sure the public key corresponding to your GitHub secret is there
   ```

### Backend not starting

1. Check logs: `sudo journalctl -u removebg-backend -n 50`
2. Verify Python virtual environment: `source /var/www/removebg/backend/venv/bin/activate && python --version`
3. Check port availability: `sudo netstat -tulpn | grep 8000`

### Frontend not loading

1. Check Nginx error logs: `sudo tail -f /var/log/nginx/error.log`
2. Verify file permissions: `sudo ls -la /var/www/html/removebg`
3. Test Nginx configuration: `sudo nginx -t`

### API connection issues

1. Verify CORS settings in `backend/main.py`
2. Check firewall rules
3. Test API directly: `curl http://localhost:8000/api/health`

## SSL/HTTPS Setup (Recommended)

Use Let's Encrypt for free SSL certificates:

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

## Monitoring

Consider setting up monitoring for:
- Backend service health
- Disk space (image processing can use temporary storage)
- Memory usage (rembg models can be memory-intensive)

## Backup

Regularly backup:
- `/var/www/removebg/backend/` - Backend code
- `/var/www/html/removebg/` - Frontend build
- Nginx configuration files

