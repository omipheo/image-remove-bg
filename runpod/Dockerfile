# Dockerfile for RunPod GPU Processing Service
FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ /app/backend/
WORKDIR /app/backend

# Expose port
EXPOSE 8001

# Set environment variables
ENV HOST=0.0.0.0
ENV PORT=8001
ENV PYTHONUNBUFFERED=1

# Run the GPU processor
CMD ["python", "gpu_processor.py"]

