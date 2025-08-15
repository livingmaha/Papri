# backend/papri_project/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
import json
from celery.schedules import crontab

# --- Core Setup ---
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT_DIR = BASE_DIR.parent
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=dotenv_path)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-fallback-key-for-development-only-change-me')
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# --- Production Mode Flag ---
# Use this single variable to control multiple production-specific settings.
PAPRI_PRODUCTION_MODE = os.getenv('PAPRI_PRODUCTION_MODE', 'False') == 'True'

# In production, DEBUG should always be False.
if PAPRI_PRODUCTION_MODE:
    DEBUG = False

ALLOWED_HOSTS_STRING = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_STRING.split(',') if host.strip()]

# --- Installed Apps ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',  # Must be before staticfiles
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'cloudinary_storage', # Add before staticfiles
    'cloudinary',

    # Third-party apps
    'rest_framework',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'django_celery_results',
    'django_celery_beat',
    'django_ratelimit',
    'drf_spectacular', # For API Docs
    'compressor'
    'cloudinary_storage',
    'django.contrib.staticfiles',
    'cloudinary',,      # For Frontend Performance

    # Local apps
    'api.apps.ApiConfig',
    'ai_agents.apps.AiAgentsConfig',
    'payments.apps.PaymentsConfig',
    'users', # Ensure users app is registered if it exists
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Whitenoise Middleware should be right after SecurityMiddleware
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'papri_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(PROJECT_ROOT_DIR, 'frontend', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'papri_project.wsgi.application'
ASGI_APPLICATION = 'papri_project.asgi.application'

# --- Database ---
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.getenv('DB_NAME', 'papri_db'),
        'USER': os.getenv('DB_USER', 'papri_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'papri_password'),
        'HOST': os.getenv('DB_HOST', 'db'), # Use service name from docker-compose
        'PORT': os.getenv('DB_PORT', '5432'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    }
}

# --- Authentication ---
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)
SITE_ID = 1
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = os.getenv('ACCOUNT_EMAIL_VERIFICATION', 'mandatory' if PAPRI_PRODUCTION_MODE else 'optional')
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = '/'
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID'),
            'secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET'),
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    }
}

# --- Password Validation ---
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Internationalization ---
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

# --- Static & Media Files ---
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(PROJECT_ROOT_DIR, 'frontend', 'static')]
STATIC_ROOT = BASE_DIR / 'staticfiles_collected'
# Add CompressorFinder for django-compressor
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'compressor.finders.CompressorFinder',
)

# Cloudinary Media Storage
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
CLOUDINARY_URL = os.getenv('CLOUDINARY_URL')

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'

MEDIA_ROOTMEDIA_URL = '/papri/media/' # This can be a virtual path
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage' = BASE_DIR / 'mediafiles_storage'

CLOUDINARY_URL = os.getenv('CLOUDINARY_URL')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Django Compressor Settings (Frontend Performance) ---
COMPRESS_ENABLED = not DEBUG
COMPRESS_OFFLINE = True # Recommended for production
COMPRESS_CSS_FILTERS = [
    'compressor.filters.css_default.CssAbsoluteFilter',
    'compressor.filters.cssmin.rCSSMinFilter',
]
COMPRESS_JS_FILTERS = [
    'compressor.filters.jsmin.JSMinFilter',
]

# --- REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework.authentication.SessionAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticatedOrReadOnly',),
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        # Only include BrowsableAPIRenderer in non-production mode
        *([ 'rest_framework.renderers.BrowsableAPIRenderer' ] if not PAPRI_PRODUCTION_MODE else [])
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.getenv('APP_DEFAULT_RESULTS_PER_PAGE', 12)),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema', # For API Docs
}

# --- API Documentation (drf-spectacular) ---
SPECTACULAR_SETTINGS = {
    'TITLE': 'PAPRI AI API',
    'DESCRIPTION': 'Official API documentation for the PAPRI AI Video Meta-Search and Editor platform.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False, # Serve schema only through designated view
    'CONTACT': {
        'name': 'PAPRI Support',
        'email': 'support@papri.example.com',
    },
}

# --- Celery ---
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# --- CORS ---
CORS_ALLOW_CREDENTIALS = True
if not PAPRI_PRODUCTION_MODE:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS_STRING = os.getenv('CORS_ALLOWED_ORIGINS')
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STRING.split(',') if origin.strip()] if CORS_ALLOWED_ORIGINS_STRING else []

# --- Security Settings (HTTPS Enforcement) ---
if PAPRI_PRODUCTION_MODE:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Ensure session cookie has httponly flag to prevent client-side script access
    SESSION_COOKIE_HTTPONLY = True
    # Sets the SameSite attribute of the CSRF cookie to prevent CSRF attacks
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SAMESITE = 'Lax'


# --- Email Backend Configuration ---
# CRITICAL: This section resolves the email backend audit point.
PAPRI_USE_CONSOLE_EMAIL = os.getenv('PAPRI_USE_CONSOLE_EMAIL', 'False') == 'True'

if DEBUG or PAPRI_USE_CONSOLE_EMAIL:
    # Use console backend for development or when explicitly requested.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    # Production: Use SMTP backend configured via environment variables.
    # Defaults are provided for common setups, but should be set in .env for production.
    EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
    EMAIL_HOST = os.getenv('EMAIL_HOST') # e.g., 'smtp.sendgrid.net' or 'email-smtp.us-east-1.amazonaws.com'
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False') == 'True' # TLS and SSL are mutually exclusive
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER') # e.g., 'apikey' for SendGrid
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD') # The actual API key or password
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'PAPRI Support <noreply@papri.example.com>')
    # Example for SendGrid:
    # EMAIL_HOST = 'smtp.sendgrid.net'
    # EMAIL_HOST_USER = 'apikey' # This is the literal string
    # EMAIL_HOST_PASSWORD = os.getenv('SENDGRID_API_KEY')
    # EMAIL_PORT = 587
    # EMAIL_USE_TLS = True
    #
    # Example for AWS SES:
    # EMAIL_HOST = 'email-smtp.us-east-1.amazonaws.com'
    # EMAIL_HOST_USER = os.getenv('AWS_SES_SMTP_USER')
    # EMAIL_HOST_PASSWORD = os.getenv('AWS_SES_SMTP_PASSWORD')
    # EMAIL_PORT = 587
    # EMAIL_USE_TLS = True

ACCOUNT_EMAIL_SUBJECT_PREFIX = '[Papri] '

# --- Logging ---
LOGGING_DIR = BASE_DIR / 'logs'
LOGGING_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {name}:{lineno} {message}', 'style': '{'},
        'simple': {'format': '{levelname} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'file_django': {
            'level': 'INFO', 'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'django.log', 'maxBytes': 10 * 1024 * 1024, 'backupCount': 5, 'formatter': 'verbose'
        },
        'file_papri_app': {
            'level': 'DEBUG', 'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'papri_app.log', 'maxBytes': 10 * 1024 * 1024, 'backupCount': 5, 'formatter': 'verbose'
        },
    },
    'root': {'handlers': ['console', 'file_django'], 'level': os.getenv('DJANGO_LOG_LEVEL_ROOT', 'WARNING')},
    'loggers': {
        'django': {'handlers': ['console', 'file_django'], 'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'), 'propagate': False},
        'api': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
        'ai_agents': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
        'payments': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
        'celery': {'handlers': ['console', 'file_papri_app'], 'level': 'INFO', 'propagate': False},
    }
}


# --- Application-Specific Settings ---
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY')
PAYSTACK_WEBHOOK_SECRET = os.getenv('PAYSTACK_WEBHOOK_SECRET')
QDRANT_URL = os.getenv('QDRANT_URL', 'http://qdrant:6333')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')
SENTENCE_TRANSFORMER_MODEL = os.getenv('SENTENCE_TRANSFORMER_MODEL', 'all-MiniLM-L6-v2')
TEXT_EMBEDDING_DIMENSION = int(os.getenv('TEXT_EMBEDDING_DIMENSION', 384))
VISUAL_CNN_MODEL_NAME = os.getenv('VISUAL_CNN_MODEL_NAME', 'EfficientNetV2S')
IMAGE_EMBEDDING_DIMENSION = int(os.getenv('IMAGE_EMBEDDING_DIMENSION', 1280))

# ... Add other app-specific settings from the original file...
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
VIMEO_ACCESS_TOKEN = os.getenv('VIMEO_ACCESS_TOKEN')
MAX_DEMO_SEARCHES = int(os.getenv('MAX_DEMO_SEARCHES', 3))
