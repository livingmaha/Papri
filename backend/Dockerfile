# backend/Dockerfile
# Base image with Python 3.11 pre-installed
FROM python:3.11-slim

# Set environment variables to prevent Python from writing .pyc files and to buffer output
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by Python packages
# For psycopg2, we need libpq-dev and postgresql-client for pg_isready
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies
COPY ./requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend application code into the container
COPY . /app/

# Ensure the entrypoint script is executable and has correct Unix line endings.
# This is a critical step for Windows developer compatibility.
RUN chmod +x /app/docker-entrypoint.sh \
    && sed -i 's/\r$//g' /app/docker-entrypoint.sh

# The entrypoint script will be executed when the container starts
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# The CMD is passed from docker-compose.yml, which will be executed by the entrypoint.
# Example CMD from docker-compose:
# gunicorn papri_project.wsgi:application --bind 0.0.0.0:8000
