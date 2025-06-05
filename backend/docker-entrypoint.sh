#!/bin/sh
# backend/docker-entrypoint.sh

set -e # Exit immediately if a command exits with a non-zero status.

echo "Running Django entrypoint script..."

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files (optional, can be done at build time if preferred)
# Ensure DEBUG is False for collectstatic in production builds
# echo "Collecting static files..."
# python manage.py collectstatic --noinput --clear

# Start Gunicorn or runserver based on the CMD
if [ "$1" = 'gunicorn' ]; then
    echo "Starting Gunicorn server..."
    exec gunicorn papri_project.wsgi:application \
        --name papri_web \
        --bind 0.0.0.0:8000 \
        --workers ${GUNICORN_WORKERS:-3} \
        --worker-class ${GUNICORN_WORKER_CLASS:-sync} \
        --log-level ${GUNICORN_LOG_LEVEL:-info} \
        --log-file=- \
        --access-logfile=- \
        --timeout ${GUNICORN_TIMEOUT:-120} \
        --keep-alive ${GUNICORN_KEEP_ALIVE:-5}
elif [ "$1" = 'runserver' ]; then
    echo "Starting Django development server..."
    exec python manage.py runserver 0.0.0.0:8000
elif [ "$1" = 'celery_worker_default' ]; then
    echo "Starting Celery default worker..."
    exec celery -A papri_project worker -l ${CELERY_LOG_LEVEL:-info} -Q default -c ${CELERY_DEFAULT_CONCURRENCY:-4} --pidfile=
elif [ "$1" = 'celery_worker_ai' ]; then
    echo "Starting Celery AI processing worker..."
    exec celery -A papri_project worker -l ${CELERY_LOG_LEVEL:-info} -Q ai_processing -c ${CELERY_AI_CONCURRENCY:-2} --pidfile=
elif [ "$1" = 'celery_worker_video' ]; then
    echo "Starting Celery video editing worker..."
    exec celery -A papri_project worker -l ${CELERY_LOG_LEVEL:-info} -Q video_editing -c ${CELERY_VIDEO_CONCURRENCY:-1} --pidfile=
elif [ "$1" = 'celery_beat' ]; then
    echo "Starting Celery beat scheduler..."
    # Ensure celerybeat-schedule.db is in a persistent volume or handle deletion on start
    rm -f /app/celerybeat.pid /app/celerybeat-schedule # Remove old schedule file and pid
    exec celery -A papri_project beat -l ${CELERY_LOG_LEVEL:-info} --scheduler django_celery_beat.schedulers:DatabaseScheduler --pidfile=/app/celerybeat.pid
else
    echo "Unknown command: $1"
    # exec "$@" # Or exit
    exit 1
fi
