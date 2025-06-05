# backend/papri_project/celery.py
import os
from celery import Celery
# from django.conf import settings # Not strictly needed here if app.config_from_object is used

# Set the default Django settings module for the 'celery' program.
# This must happen before importing tasks or anything that might import Django settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'papri_project.settings')

# Create a Celery application instance
# The first argument is the name of the current module ('papri_project' here)
# This name is also used by default for the main Celery queue (if not overridden)
app = Celery('papri_project')

# Configure Celery using settings from Django settings.py.
# The CELERY_ namespace means all Celery configuration options
# must have a `CELERY_` prefix in settings.py (e.g., CELERY_BROKER_URL).
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
# Celery will automatically discover tasks in files named 'tasks.py'
# within each app listed in INSTALLED_APPS.
app.autodiscover_tasks()

# Optional: Define a simple debug task to test worker connectivity
@app.task(bind=True, name='papri_project.debug_task')
def debug_task(self):
    from django.conf import settings as django_settings # Import here to ensure settings are loaded
    print(f'Request: {self.request!r}')
    logger_name = self.app.conf.task_default_queue or 'default'
    print(f'This debug task is running on queue: {logger_name}')
    print(f"Celery Debug Task: Django TIME_ZONE is: {django_settings.TIME_ZONE}")
    return "Celery debug task executed successfully."

# If you have periodic tasks defined via CELERY_BEAT_SCHEDULE in settings.py,
# and use django-celery-beat, they will be picked up automatically.
