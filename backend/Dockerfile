# backend/Dockerfile

# --- Base Stage ---
# Use an official Python runtime as a parent image
FROM python:3.10-slim-bookworm AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PIP_NO_CACHE_DIR off
ENV PIP_DISABLE_PIP_VERSION_CHECK on

# Set work directory
WORKDIR /app

# Install system dependencies required for building Python packages
# and for MySQL client, OpenCV, etc.
# You might need to adjust these based on your specific requirements.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \       # For compiling some Python packages
    libmysqlclient-dev \    # For mysqlclient
    libjpeg-dev \           # For Pillow
    zlib1g-dev \            # For Pillow
    libpq-dev \             # If you were to switch to PostgreSQL
    libffi-dev \            # For cffi, a dependency of some crypto libs
    # OpenCV dependencies
    libgl1-mesa-glx \
    libglib2.0-0 \
    # For yt-dlp/ffmpeg if downloading/processing directly in Docker,
    # otherwise, if these are handled by external services or pre-downloaded,
    # you might not need ffmpeg here.
    ffmpeg \
    # For Scrapy/lxml (if not already covered by build-essential)
    libxml2-dev libxslt1-dev \
    # Cleanup
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Builder Stage (for Python dependencies) ---
FROM base AS builder

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
# Using a virtual environment within the builder stage can be good practice
# but for simplicity in this Dockerfile, installing directly.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Runtime Stage ---
FROM base AS runtime

# Set work directory (already set in base, but good for clarity)
WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy the Django application code into the container
# This assumes your Dockerfile is in the `backend` directory.
COPY . .

# Create directories for static files and media files if they are managed by Django app container
# These will be populated by collectstatic or user uploads.
RUN mkdir -p /app/staticfiles_collected /app/mediafiles_storage && \
    chown -R www-data:www-data /app/staticfiles_collected /app/mediafiles_storage
# Note: `www-data` is a common user for web servers. Adjust if your base image uses a different user or if you create one.
# For simplicity, we'll run as root in dev, but for prod, a non-root user is better.

# Expose the port the app runs on (e.g., Gunicorn will run on this port)
EXPOSE 8000

# Default command to run when the container starts (can be overridden in docker-compose.yml)
# This is just a placeholder; Gunicorn or Daphne will be the entrypoint in docker-compose.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
