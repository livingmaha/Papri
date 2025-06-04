# backend/papri_project/asgi.py
"""
ASGI config for papri_project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/stable/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'papri_project.settings')

# Get the default Django ASGI application
django_asgi_app = get_asgi_application()

# If you were using Django Channels, you would wrap it here:
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.auth import AuthMiddlewareStack
# import your_app.routing # Assuming you have WebSocket routings

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AuthMiddlewareStack(
#         URLRouter(
#             your_app.routing.websocket_urlpatterns
#         )
#     ),
# })

# For now, just the HTTP application:
application = django_asgi_app
