# backend/Dockerfile

# --- Base Stage ---
# Use an official Python runtime as a parent image
FROM python:3.10-slim-buster AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# System dependencies
# Install build dependencies for common Python packages and MySQL client
# Also install ffmpeg for MoviePy and other potential video processing tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
        # For Pillow (optional, but good to have common image format support)
        libjpeg-dev zlib1g-dev libtiff-dev libfreetype6-dev liblcms2-dev libwebp-dev \
        # For OpenCV headless (if not using opencv-python-headless, which is preferred)
        # libgl1-mesa-glx libglib2.0-0
        # For video processing (ffmpeg is crucial for MoviePy)
        ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Builder Stage (for installing Python dependencies) ---
FROM base AS builder

# Set work directory
WORKDIR /app_build

# Install poetry (optional, if you use poetry for dependency management)
# RUN pip install poetry
# COPY poetry.lock pyproject.toml ./
# RUN poetry config virtualenvs.create false && poetry install --no-dev --no-interaction --no-ansi

# If using requirements.txt:
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn # Install Gunicorn here

# --- Final Stage ---
FROM base AS final

# Create a non-root user and group
ARG APP_USER=papriuser
ARG APP_GROUP=paprigroup
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} ${APP_GROUP} \
    && useradd -u ${UID} -g ${APP_GROUP} -s /bin/sh -m ${APP_USER}

# Set work directory
WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy application code
# Ensure .dockerignore is properly set up to exclude venv, .git, etc.
COPY . .

# Create directories for static files, media files, and logs if they are within the app dir
# These might be better handled by volumes in docker-compose for persistence
RUN mkdir -p /app/staticfiles_collected /app/mediafiles_storage /app/logs \
    && chown -R ${APP_USER}:${APP_GROUP} /app

# Change to non-root user
USER ${APP_USER}

# Collect static files (ensure this is run after code is copied and user is set if needed for permissions)
# This will collect into STATIC_ROOT defined in settings.py (e.g., /app/staticfiles_collected)
# Ensure DEBUG=False when running collectstatic in a production-like build
# RUN python manage.py collectstatic --noinput --clear

# Expose port (Gunicorn will run on this port inside the container)
EXPOSE 8000

# Default command to run when container starts
# Gunicorn for production. Ensure papri_project.wsgi points to your WSGI application.
# CMD ["gunicorn", "papri_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
# For development, you might use:
# CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
# A separate entrypoint script (entrypoint.sh) is often better for running migrations then gunicorn.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn"] # Default command for entrypoint script
