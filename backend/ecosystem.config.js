module.exports = {
  apps: [{
    name: 'image-remove-bg-api',
    script: './start_backend.sh',
    interpreter: 'bash',
    cwd: '/root/image-remove-bg/backend',
    env: {
      NODE_ENV: 'production',
      LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
      PATH: process.env.PATH,
      PYTHONUNBUFFERED: '1'
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    log_file: './logs/combined.log',
    time: true,
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '2G',
    exec_mode: 'fork'
  }]
};
