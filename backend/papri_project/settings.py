# backend/papri_project/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
import json # For parsing SCRAPEABLE_PLATFORMS_JSON

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent # Points to 'backend' directory
PROJECT_ROOT_DIR = BASE_DIR.parent # Points to 'papri_project_root'

# Load .env from the backend directory (papri_project_root/backend/.env)
dotenv_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=dotenv_path)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-fallback-key-for-development-only-change-me')
DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS_STRING = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_STRING.split(',') if host.strip()]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites', # Required by allauth

    # Third-party apps
    'rest_framework',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google', # Example provider
    'django_celery_results', # For storing Celery task results in DB
    'django_celery_beat',    # For periodic tasks

    # Papri apps
    'api.apps.ApiConfig',
    'ai_agents.apps.AiAgentsConfig', # If ai_agents has models or admin integration
    'payments.apps.PaymentsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # For serving static files in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware', # Must be before CommonMiddleware
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware', # Allauth middleware for account management
]

ROOT_URLCONF = 'papri_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Correct path to frontend/templates
        'DIRS': [os.path.join(PROJECT_ROOT_DIR, 'frontend', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request', # Required by allauth
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.static',
                'django.template.context_processors.media',
            ],
        },
    },
]

WSGI_APPLICATION = 'papri_project.wsgi.application' # If using WSGI
ASGI_APPLICATION = 'papri_project.asgi.application' # If using ASGI (e.g., for Django Channels)

# Database
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.mysql'),
        'NAME': os.getenv('DB_NAME', 'papri_db'),
        'USER': os.getenv('DB_USER', 'papri_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'papri_password'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'), # Or your DB host
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            # Recommended for MySQL with Django:
            # 'sql_mode': 'TRADITIONAL,NO_AUTO_VALUE_ON_ZERO',
            # 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Authentication Settings
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',       # Default Django auth
    'allauth.account.auth_backends.AuthenticationBackend', # Allauth specific
)
SITE_ID = 1 # Required by Django Sites framework (used by allauth)

ACCOUNT_USER_MODEL_USERNAME_FIELD = None # No username, use email
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email' # Users log in with email
ACCOUNT_EMAIL_VERIFICATION = os.getenv('ACCOUNT_EMAIL_VERIFICATION', 'optional') # 'mandatory', 'optional', 'none'
ACCOUNT_ADAPTER = 'allauth.account.adapter.DefaultAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'allauth.socialaccount.adapter.DefaultSocialAccountAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True # Automatically create user if social account verified
SOCIALACCOUNT_EMAIL_VERIFICATION = ACCOUNT_EMAIL_VERIFICATION
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID'),
            'secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET'),
            'key': '' # Not typically used by Google provider but required by allauth structure
        }
        # Add 'VERIFIED_EMAIL': True if you only want to allow verified Google emails
    }
}
LOGIN_URL = '/accounts/login/' # Allauth's login page
LOGIN_REDIRECT_URL = '/app/'  # Redirect here after successful login
LOGOUT_REDIRECT_URL = '/'     # Redirect here after logout

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Nairobi') # Example
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
# Location of static files in your frontend app (collected by collectstatic)
STATICFILES_DIRS = [os.path.join(PROJECT_ROOT_DIR, 'frontend', 'static')]
# Location where collectstatic will gather all static files for deployment
STATIC_ROOT = os.path.join(PROJECT_ROOT_DIR, 'staticfiles_collected')
# Use WhiteNoise for serving static files in production if not using S3/CDN directly
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# Media files (User uploads)
MEDIA_URL = '/media/'
# MEDIA_ROOT is where user-uploaded files will be stored.
# Ensure this directory is writable by the Django/Celery process.
MEDIA_ROOT = os.path.join(BASE_DIR, 'mediafiles_storage') # e.g., papri_project_root/backend/mediafiles_storage/

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        # Add JWT or TokenAuthentication if you plan to use them for mobile/external apps
        # 'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly', # Default policy
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        ('rest_framework.renderers.BrowsableAPIRenderer' if DEBUG else None),
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10, # Default number of items per page
    'PAGE_SIZE_QUERY_PARAM': 'page_size', # Allow client to override page size
    'MAX_PAGE_SIZE': 100,
}

# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'django-db') # Uses django_celery_results
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE # Use Django's timezone
CELERY_TASK_TRACK_STARTED = True # To see 'STARTED' state in admin/flower
CELERY_RESULT_EXTENDED = True   # Store more task metadata
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler' # For periodic tasks

# CORS Settings
CORS_ALLOW_CREDENTIALS = True # Allow cookies to be sent with CORS requests
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True # For local development ease
    # Alternatively, for more control in dev:
    # CORS_ALLOWED_ORIGINS = [
    #     "http://localhost:8000",
    #     "http://127.0.0.1:8000",
    # ]
else:
    CORS_ALLOWED_ORIGINS_STRING = os.getenv('CORS_ALLOWED_ORIGINS')
    if CORS_ALLOWED_ORIGINS_STRING:
        CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STRING.split(',') if origin.strip()]
    else:
        CORS_ALLOWED_ORIGINS = [] # Define your production frontend domain(s) here

# Logging Configuration (Example)
LOGGING_DIR = BASE_DIR / 'logs'
LOGGING_DIR.mkdir(parents=True, exist_ok=True) # Ensure logs directory exists

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module}:{lineno} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file_django': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'django.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_papri_app': {
            'level': 'DEBUG', # More verbose for our app
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGING_DIR / 'papri_app.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'root': { # Catch-all logger
        'handlers': ['console', 'file_django'],
        'level': os.getenv('DJANGO_LOG_LEVEL_ROOT', 'WARNING'),
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_django'],
            'level': os.getenv('DJANGO_LOG_LEVEL_DJANGO', 'INFO'),
            'propagate': False,
        },
        'api': { # Logger for your 'api' app
            'handlers': ['console', 'file_papri_app'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'ai_agents': { # Logger for your 'ai_agents'
            'handlers': ['console', 'file_papri_app'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'payments': { # Logger for your 'payments' app
            'handlers': ['console', 'file_papri_app'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': { # For Celery specific logs
            'handlers': ['console', 'file_papri_app'],
            'level': 'INFO',
            'propagate': False,
        },
        # Silence noisy loggers if needed
        # 'some_noisy_third_party_logger': {
        #     'handlers': ['console'],
        #     'level': 'WARNING',
        #     'propagate': False,
        # },
    },
}

# --- Papri Specific Settings ---

# External Service API Keys (loaded from .env)
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
VIMEO_CLIENT_ID = os.getenv('VIMEO_CLIENT_ID')
VIMEO_CLIENT_SECRET = os.getenv('VIMEO_CLIENT_SECRET')
VIMEO_ACCESS_TOKEN = os.getenv('VIMEO_ACCESS_TOKEN')
DAILYMOTION_API_URL = os.getenv('DAILYMOTION_API_URL', 'https://api.dailymotion.com')

# Paystack Settings
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY')
PAYSTACK_CALLBACK_URL_NAME = 'payments:paystack_callback'
PAYMENT_SUCCESS_REDIRECT_URL = os.getenv('PAYMENT_SUCCESS_REDIRECT_URL', '/app/#payment-success')
PAYMENT_FAILED_REDIRECT_URL = os.getenv('PAYMENT_FAILED_REDIRECT_URL', '/app/#payment-failed')
SIGNUP_CODE_EXPIRY_DAYS = int(os.getenv('SIGNUP_CODE_EXPIRY_DAYS', 7))

# Vector DB (Qdrant) Settings
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333)) # HTTP port
QDRANT_GRPC_PORT = int(os.getenv('QDRANT_GRPC_PORT', 6334)) # gRPC port (optional, if using gRPC client)
QDRANT_URL = os.getenv('QDRANT_URL', f"http://{QDRANT_HOST}:{QDRANT_PORT}") # Default constructed URL
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', None) # Optional API key
QDRANT_PREFER_GRPC = os.getenv('QDRANT_PREFER_GRPC', 'False') == 'True'
QDRANT_TIMEOUT_SECONDS = int(os.getenv('QDRANT_TIMEOUT_SECONDS', 20))

QDRANT_TRANSCRIPT_COLLECTION_NAME = os.getenv('QDRANT_TRANSCRIPT_COLLECTION_NAME', 'papri_transcripts_v1')
QDRANT_VISUAL_COLLECTION_NAME = os.getenv('QDRANT_VISUAL_COLLECTION_NAME', 'papri_visuals_v1')

# Embedding Model Dimensions (Crucial for Qdrant collection creation)
# These should match the output dimensions of your models.
# Example: SentenceTransformer 'all-MiniLM-L6-v2' has dim 384.
# EfficientNetV2S (pooling='avg') output dim depends on specific S, M, L variant, e.g., 1280 for S.
# Check your model's documentation.
TEXT_EMBEDDING_DIMENSION = int(os.getenv('TEXT_EMBEDDING_DIMENSION', 384)) # Example for all-MiniLM-L6-v2
IMAGE_EMBEDDING_DIMENSION = int(os.getenv('IMAGE_EMBEDDING_DIMENSION', 1280)) # Example for EfficientNetV2S (with avg pooling)

# AI Model Names
SENTENCE_TRANSFORMER_MODEL = os.getenv('SENTENCE_TRANSFORMER_MODEL', 'all-MiniLM-L6-v2')
VISUAL_CNN_MODEL_NAME = os.getenv('VISUAL_CNN_MODEL_NAME', 'EfficientNetV2S') # Or "ResNet50"
# For MoviePy editor
MOVIEPY_THREADS = int(os.getenv('MOVIEPY_THREADS', 4))
MOVIEPY_PRESET = os.getenv('MOVIEPY_PRESET', 'medium') # ffmpeg preset: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow


# Scraper settings
MAX_API_RESULTS_PER_SOURCE = int(os.getenv('MAX_API_RESULTS_PER_SOURCE', 10)) # Increased default
MAX_SCRAPED_ITEMS_PER_SOURCE = int(os.getenv('MAX_SCRAPED_ITEMS_PER_SOURCE', 5)) # Increased default
SCRAPE_INTER_PLATFORM_DELAY_SECONDS = int(os.getenv('SCRAPE_INTER_PLATFORM_DELAY_SECONDS', 2)) # Increased politeness

# Load SCRAPEABLE_PLATFORMS from JSON string in .env
try:
    SCRAPEABLE_PLATFORMS_JSON = os.getenv('SCRAPEABLE_PLATFORMS_JSON', '[]')
    SCRAPEABLE_PLATFORMS_CONFIG = json.loads(SCRAPEABLE_PLATFORMS_JSON)
except json.JSONDecodeError:
    SCRAPEABLE_PLATFORMS_CONFIG = []
    if DEBUG: # Add a default for dev if parsing fails or env var is missing
        SCRAPEABLE_PLATFORMS_CONFIG.append({
            'name': 'PeerTube_Tilvids_Dev_Example',
            'spider_name': 'peertube', # Name of the Scrapy spider
            'base_url': 'https://tilvids.com',
            'search_path_template': '/api/v1/search/videos?search={query}&count={max_results}&sort=-match', # Example API
            'default_listing_url': 'https://tilvids.com/videos/recently-added',
            'is_active': True,
            'platform_identifier': 'peertube_tilvids' # Used to tag data from this specific instance
        })
        print("Warning: SCRAPEABLE_PLATFORMS_JSON not found or invalid in .env. Using default dev config.")

# Email settings for Django Allauth (e.g., for password reset, email verification)
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend') # Default to console for dev
EMAIL_HOST = os.getenv('EMAIL_HOST') # e.g., 'smtp.example.com'
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER') # Your SMTP username
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD') # Your SMTP password
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Papri Support <noreply@yourpaprisite.com>')
ACCOUNT_EMAIL_SUBJECT_PREFIX = '[Papri] ' # Subject prefix for emails sent by django-allauth

# Base URL for constructing absolute URLs (used by allauth for email links)
# In production, set this to your actual domain.
PAPRI_BASE_URL = os.getenv('PAPRI_BASE_URL', 'http://localhost:8000')

# API URL for frontend (can be relative if frontend is served by Django, or absolute if separate)
API_BASE_URL_FRONTEND = os.getenv('API_BASE_URL_FRONTEND', '') # Empty means relative paths for JS

# Maximum download size for videos in MB (for CAAgent)
MAX_DOWNLOAD_FILE_SIZE_MB = int(os.getenv('MAX_DOWNLOAD_FILE_SIZE_MB', 200)) # Default to 200MB

# Default number of results to show per page in the app (can be overridden by user)
APP_DEFAULT_RESULTS_PER_PAGE = int(os.getenv('APP_DEFAULT_RESULTS_PER_PAGE', 9))

# Maximum number of trial searches for anonymous users from landing page
MAX_DEMO_SEARCHES = int(os.getenv('MAX_DEMO_SEARCHES', 3))
