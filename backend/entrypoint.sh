#!/bin/sh
# backend/entrypoint.sh

# Exit immediately if a command exits with a non-zero status.
set -e

echo "Waiting for PostgreSQL to be available..."
# This is a simple wait script. For robust production, use a tool like docker-compose-wait.
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 1
done
echo "PostgreSQL started"

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start the Gunicorn server
# The --bind 0.0.0.0:8000 makes it accessible from other Docker containers.
# The number of workers can be tuned. A common formula is (2 * number of CPU cores) + 1.
exec gunicorn papri_project.wsgi:application --bind 0.0.0.0:8000 --workers 3
