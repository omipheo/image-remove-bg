# Multi-GPU Setup - Manual PM2 Startup

## Quick Start

**First, stop any old processes:**
```bash
# Stop old manually-started workers (if any)
pkill -f "python3 main.py"

# Stop PM2 processes (if running)
pm2 stop all
# OR if PM2 not in PATH:
# /usr/bin/pm2 stop all
# OR find PM2: find /usr -name pm2 2>/dev/null
```

**Then start with PM2:**
```bash
cd /root/image-remove-bg/backend

# Start 4 GPU workers
pm2 start ecosystem.multi-gpu.config.js

# Start load balancer
pm2 start ecosystem.load-balancer.config.js

# Check status
pm2 list
```

**If PM2 is not in PATH:**
```bash
# Find PM2 location
which pm2 || find /usr -name pm2 2>/dev/null || find /root -name pm2 2>/dev/null

# Use full path, e.g.:
/usr/bin/pm2 start ecosystem.multi-gpu.config.js
```

## PM2 Commands

```bash
pm2 list                          # Show all processes
pm2 logs                          # Show all logs
pm2 logs load-balancer            # Show load balancer logs
pm2 logs image-remove-bg-gpu-0    # Show GPU 0 worker logs
pm2 stop all                      # Stop all processes
pm2 restart all                   # Restart all processes
pm2 delete all                    # Remove all from PM2
```

## Architecture

- **4 GPU Workers**: Ports 8001-8004 (one per GPU)
- **Load Balancer**: Port 8000 (distributes connections)
- **Nginx**: Port 443 (proxies to load balancer on 8000)

## Files

- `ecosystem.multi-gpu.config.js` - PM2 config for 4 GPU workers
- `ecosystem.load-balancer.config.js` - PM2 config for load balancer
- `start_multi_gpu.sh` - Script used by PM2 to start individual workers
- `load_balancer.py` - Load balancer code

