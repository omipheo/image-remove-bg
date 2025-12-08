#!/usr/bin/env python3
"""
Script to update nginx configuration for WebSocket support
"""
import os
import sys
import shutil
from pathlib import Path

def find_nginx_config():
    """Find the active nginx configuration file"""
    possible_locations = [
        "/etc/nginx/sites-available/image-remove-bg",
        "/etc/nginx/conf.d/image-remove-bg.conf",
        "/etc/nginx/sites-available/default",
    ]
    
    # Also check all files in sites-available and conf.d
    for directory in ["/etc/nginx/sites-available", "/etc/nginx/conf.d"]:
        if os.path.exists(directory):
            for file in os.listdir(directory):
                if file.endswith('.conf') or not file.startswith('.'):
                    full_path = os.path.join(directory, file)
                    if os.path.isfile(full_path):
                        try:
                            with open(full_path, 'r') as f:
                                content = f.read()
                                if '8000' in content or 'image-remove-bg' in content or '/var/www/image-remove-bg' in content:
                                    return full_path
                        except:
                            pass
    
    return None

def update_nginx_config(config_path):
    """Update nginx config to include WebSocket support"""
    
    # Read current config
    with open(config_path, 'r') as f:
        content = f.read()
    
    # Check if WebSocket location already exists
    if 'location /ws/' in content:
        print(f"✓ WebSocket location already exists in {config_path}")
        if 'Upgrade $http_upgrade' in content and 'Connection "upgrade"' in content:
            print("✓ WebSocket configuration looks correct")
            return True
        else:
            print("⚠ WebSocket location exists but may be missing required headers")
            return False
    
    # Create backup
    backup_path = f"{config_path}.backup"
    shutil.copy2(config_path, backup_path)
    print(f"Created backup: {backup_path}")
    
    # WebSocket location block
    ws_block = """    # WebSocket proxy for pipelined processing
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # WebSocket timeouts (longer for batch processing)
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }

"""
    
    # Insert before /api location
    if 'location /api' in content:
        lines = content.split('\n')
        new_lines = []
        inserted = False
        
        for i, line in enumerate(lines):
            # Insert WebSocket block before /api location
            if 'location /api' in line and not inserted:
                # Add WebSocket block
                for ws_line in ws_block.rstrip().split('\n'):
                    new_lines.append(ws_line)
                inserted = True
            new_lines.append(line)
        
        new_content = '\n'.join(new_lines)
        
        # Write updated config
        with open(config_path, 'w') as f:
            f.write(new_content)
        
        print(f"✓ Added WebSocket location block to {config_path}")
        return True
    else:
        print(f"⚠ Could not find 'location /api' in {config_path}")
        print("Please manually add the WebSocket configuration")
        return False

def main():
    print("=== Updating Nginx Configuration for WebSocket ===")
    print()
    
    # Check if running as root
    if os.geteuid() != 0:
        print("Error: This script must be run as root (use sudo)")
        sys.exit(1)
    
    # Find nginx config
    config_path = find_nginx_config()
    
    if not config_path:
        print("No existing nginx config found for image-remove-bg")
        print("Creating new config at /etc/nginx/sites-available/image-remove-bg")
        
        # Use the complete config file
        source_config = "/root/image-remove-bg/nginx-image-remove-bg.conf"
        target_config = "/etc/nginx/sites-available/image-remove-bg"
        
        if os.path.exists(source_config):
            shutil.copy2(source_config, target_config)
            print(f"✓ Created config: {target_config}")
            config_path = target_config
        else:
            print(f"Error: Source config not found: {source_config}")
            sys.exit(1)
    else:
        print(f"Found nginx config: {config_path}")
    
    # Update config
    if update_nginx_config(config_path):
        print()
        print("✓ Configuration updated successfully")
        print()
        print("Next steps:")
        print("1. Test nginx configuration: sudo nginx -t")
        print("2. If test passes, reload nginx: sudo nginx -s reload")
        print()
        
        # Try to enable the site if it's in sites-available
        if 'sites-available' in config_path:
            site_name = os.path.basename(config_path)
            enabled_path = f"/etc/nginx/sites-enabled/{site_name}"
            if not os.path.exists(enabled_path):
                os.symlink(config_path, enabled_path)
                print(f"✓ Enabled site: {enabled_path}")
    else:
        print("⚠ Configuration update had issues")
        sys.exit(1)

if __name__ == "__main__":
    main()
