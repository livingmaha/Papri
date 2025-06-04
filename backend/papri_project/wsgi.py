# backend/papri_project/wsgi.py
"""
WSGI config for papri_project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'papri_project.settings')

application = get_wsgi_application()

# If using Whitenoise for static files in production (recommended for simplicity)
# from whitenoise import WhiteNoise
# application = WhiteNoise(application)
# application.add_files("/path/to/your/static/files", prefix="static/") # If STATIC_ROOT is not enough
