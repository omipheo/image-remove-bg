module.exports = {
  apps: [{
    name: 'load-balancer',
    script: 'load_balancer.py',
    interpreter: 'python3',
    cwd: '/root/image-remove-bg/backend',
    env: {
      NODE_ENV: 'production',
      LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
      PATH: process.env.PATH,
      PYTHONUNBUFFERED: '1',
      PORT: '8000',  // Internal port - nginx will proxy 443 -> 8000
      HOST: '0.0.0.0'
    },
    error_file: './logs/err-load-balancer.log',
    out_file: './logs/out-load-balancer.log',
    log_file: './logs/combined-load-balancer.log',
    time: true,
    instances: 1,
    autorestart: true,
    watch: false,
    exec_mode: 'fork'
  }]
};

