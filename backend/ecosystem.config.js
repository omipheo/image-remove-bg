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
      CORS_ORIGINS: 'http://161.184.141.187,http://161.184.141.187:43752,https://161.184.141.187,https://161.184.141.187:43930,http://localhost,http://localhost:80,http://127.0.0.1,https://localhost,https://127.0.0.1',
      WORKERS: '1'
    },
    error_file: '/var/log/image-remove-bg/error.log',
    out_file: '/var/log/image-remove-bg/out.log',
    log_file: '/var/log/image-remove-bg/combined.log',
    time: true,
    autorestart: true,
    watch: false,
    max_memory_restart: '4G',  // Increased for PyTorch model processing
    merge_logs: true,
    kill_timeout: 10000,
    wait_ready: true,
    listen_timeout: 10000,
    shutdown_with_message: true
  }]
};
