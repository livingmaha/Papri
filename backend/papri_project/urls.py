# backend/papri_project/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView # For serving frontend's index.html

# Import the view that serves the main SPA (papriapp.html)
# Assuming this view is in api.views for now, or a dedicated core app
from api.views import papri_app_view

urlpatterns = [
    path('admin/', admin.site.urls), # Django admin interface

    # API endpoints (namespaced)
    path('api/', include('api.urls', namespace='api')),

    # Payment endpoints (namespaced)
    path('payments/', include('payments.urls', namespace='payments')),

    # Django Allauth URLs for authentication (login, signup, password reset, social auth, etc.)
    # These typically include:
    # /accounts/login/
    # /accounts/logout/
    # /accounts/signup/
    # /accounts/password/reset/
    # /accounts/google/login/ (if Google provider is configured)
    # ... and many more.
    path('accounts/', include('allauth.urls')),

    # Frontend Serving:
    # The main single-page application (SPA) host page (e.g., papriapp.html)
    # This should be protected by login if the app is not public.
    # The 'papri_app_main' view should render the template containing your JS app.
    path('app/', papri_app_view, name='papri_app_main'), # View that renders papriapp.html
    
    # Fallback for SPA routing on the /app/ path if using client-side routing deeply
    # For example, if your JS router handles /app/history, /app/settings etc.
    # This regex ensures that any subpath of /app/ (not matching other patterns above)
    # also serves papriapp.html. This requires careful ordering.
    # re_path(r'^app/.*$', papri_app_view, name='papri_app_spa_fallback'),


    # Landing Page - Serve index.html from frontend/templates/ at the root
    # This should be publicly accessible.
    path('', TemplateView.as_view(template_name="index.html"), name='landing_page'),

    # If you have other specific HTML pages served by Django (e.g., terms, privacy) add them here.
    # path('terms/', TemplateView.as_view(template_name="terms.html"), name='terms_page'),
]

# Serve static and media files during development
if settings.DEBUG:
    # Static files (CSS, JavaScript, Images from STATICFILES_DIRS)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT if settings.STATIC_ROOT else None) # Check if STATIC_ROOT is set
    # The above line with STATIC_ROOT is more for when `collectstatic` has been run.
    # For development, Django's runserver automatically serves from STATICFILES_DIRS if `django.contrib.staticfiles` is in INSTALLED_APPS.
    # So, explicitly adding static() for STATIC_URL might be redundant with runserver but harmless.
    
    # Media files (user uploads from MEDIA_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# It's good practice to ensure that if STATIC_ROOT is used in static(), it's actually populated.
# For development, Django's default static file serving for runserver is often sufficient without the explicit static() call for STATIC_URL.
# The static() for MEDIA_URL is standard for development.
