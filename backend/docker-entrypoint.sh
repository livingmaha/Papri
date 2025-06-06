#!/bin/sh
# NOTE: This script must be saved with LF (Unix) line endings to work correctly inside the container.
# The .gitattributes file in the repo root should enforce this.
# backend/docker-entrypoint.sh

set -e # Exit immediately if a command exits with a non-zero status.

echo "Running Django entrypoint script..."

# Wait for the database to be ready
python manage.py wait_for_db --retries 10

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files for Whitenoise
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

# Compress static files (JS/CSS) for production
# This command is guarded by COMPRESS_OFFLINE=True in settings.py
echo "Compressing static files..."
python manage.py compress --force

# Start the main process (Gunicorn, Celery worker, etc.) passed as CMD
echo "Starting main process: <span class="math-inline">@"
exec "</span>@"
