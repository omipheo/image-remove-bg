module.exports = {
  apps: [
    // GPU 0 worker
    {
      name: 'image-remove-bg-gpu-0',
      script: './start_multi_gpu.sh',
      interpreter: 'bash',
      cwd: '/root/image-remove-bg/backend',
      env: {
        NODE_ENV: 'production',
        LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
        PATH: process.env.PATH,
        PYTHONUNBUFFERED: '1',
        GPU_ID: '0',
        CUDA_VISIBLE_DEVICES: '0',
        PORT: '8001',
        HOST: '0.0.0.0'
      },
      error_file: './logs/err-gpu-0.log',
      out_file: './logs/out-gpu-0.log',
      log_file: './logs/combined-gpu-0.log',
      time: true,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '8G',
      exec_mode: 'fork'
    },
    // GPU 1 worker
    {
      name: 'image-remove-bg-gpu-1',
      script: './start_multi_gpu.sh',
      interpreter: 'bash',
      cwd: '/root/image-remove-bg/backend',
      env: {
        NODE_ENV: 'production',
        LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
        PATH: process.env.PATH,
        PYTHONUNBUFFERED: '1',
        GPU_ID: '1',
        CUDA_VISIBLE_DEVICES: '1',
        PORT: '8002',
        HOST: '0.0.0.0'
      },
      error_file: './logs/err-gpu-1.log',
      out_file: './logs/out-gpu-1.log',
      log_file: './logs/combined-gpu-1.log',
      time: true,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '8G',
      exec_mode: 'fork'
    },
    // GPU 2 worker
    {
      name: 'image-remove-bg-gpu-2',
      script: './start_multi_gpu.sh',
      interpreter: 'bash',
      cwd: '/root/image-remove-bg/backend',
      env: {
        NODE_ENV: 'production',
        LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
        PATH: process.env.PATH,
        PYTHONUNBUFFERED: '1',
        GPU_ID: '2',
        CUDA_VISIBLE_DEVICES: '2',
        PORT: '8003',
        HOST: '0.0.0.0'
      },
      error_file: './logs/err-gpu-2.log',
      out_file: './logs/out-gpu-2.log',
      log_file: './logs/combined-gpu-2.log',
      time: true,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '8G',
      exec_mode: 'fork'
    },
    // GPU 3 worker
    {
      name: 'image-remove-bg-gpu-3',
      script: './start_multi_gpu.sh',
      interpreter: 'bash',
      cwd: '/root/image-remove-bg/backend',
      env: {
        NODE_ENV: 'production',
        LD_LIBRARY_PATH: '/usr/local/cuda-12.8/targets/x86_64-linux/lib:/usr/local/cuda/lib64',
        PATH: process.env.PATH,
        PYTHONUNBUFFERED: '1',
        GPU_ID: '3',
        CUDA_VISIBLE_DEVICES: '3',
        PORT: '8004',
        HOST: '0.0.0.0'
      },
      error_file: './logs/err-gpu-3.log',
      out_file: './logs/out-gpu-3.log',
      log_file: './logs/combined-gpu-3.log',
      time: true,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '8G',
      exec_mode: 'fork'
    }
  ]
};

