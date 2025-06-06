# backend/papri_project/urls.py
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from api.views import papri_app_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls', namespace='api')),
    
    # API Schema and Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('payments/', include('payments.urls', namespace='payments')),
    path('accounts/', include('allauth.urls')),
    
    # Frontend App Views
    path('app/', papri_app_view, name='papri_app_main'),
    re_path(r'^app/.*$', papri_app_view, name='papri_app_spa_fallback'),
    
    # Legal Pages
    path('legal/privacy-policy/', TemplateView.as_view(template_name="legal/privacy_policy.html"), name='privacy_policy'),
    path('legal/terms-of-service/', TemplateView.as_view(template_name="legal/terms_of_service.html"), name='terms_of_service'),

    # Landing Page
    path('', TemplateView.as_view(template_name="index.html"), name='landing_page'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
