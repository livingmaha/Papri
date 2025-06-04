# backend/papri_project/celery.py
import os
from celery import Celery
from django.conf import settings # To access Django settings

# Set the default Django settings module for the 'celery' program.
# This must happen before importing settings or tasks.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'papri_project.settings')

# Create a Celery application instance named 'papri_project' (or any name you prefer)
app = Celery('papri_project')

# Configure Celery using settings from Django settings.py.
# The CELERY_ namespace means all Celery configuration options
# must have a `CELERY_` prefix in settings.py.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
# Celery will automatically discover tasks in files named 'tasks.py'
# within each app listed in INSTALLED_APPS.
app.autodiscover_tasks()

# Example debug task (optional, can be removed)
@app.task(bind=True, name='papri_project.debug_task')
def debug_task(self):
    print(f'Request: {self.request!r}')
    # Log Django settings to verify Celery worker has access (for debugging)
    # from django.conf import settings as django_settings
    # print(f"Celery Debug Task: Django SECRET_KEY starts with: {django_settings.SECRET_KEY[:5]}")

# If you have periodic tasks defined in settings.py (CELERY_BEAT_SCHEDULE),
# Celery Beat will pick them up.
# Alternatively, you can define them programmatically here if preferred,
# but using django-celery-beat with DatabaseScheduler is often more flexible.

# Example of a shared task (though tasks are typically in app-specific tasks.py)
# @shared_task
# def add(x, y):
#   return x + y
