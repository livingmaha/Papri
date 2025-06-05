# backend/papri_project/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
import json
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT_DIR = BASE_DIR.parent
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
    'django.contrib.sites',
    'rest_framework',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'django_celery_results',
    'django_celery_beat',
    'django_ratelimit',
    'api.apps.ApiConfig',
    'ai_agents.apps.AiAgentsConfig',
    'payments.apps.PaymentsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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
                'django.template.context_processors.static',
                'django.template.context_processors.media',
            ],
        },
    },
]

WSGI_APPLICATION = 'papri_project.wsgi.application'
ASGI_APPLICATION = 'papri_project.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.mysql'),
        'NAME': os.getenv('DB_NAME', 'papri_db'),
        'USER': os.getenv('DB_USER', 'papri_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'papri_password'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
    }
}

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)
SITE_ID = 1
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = os.getenv('ACCOUNT_EMAIL_VERIFICATION', 'optional')
ACCOUNT_ADAPTER = 'allauth.account.adapter.DefaultAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'allauth.socialaccount.adapter.DefaultSocialAccountAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = ACCOUNT_EMAIL_VERIFICATION
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'APP': {
            'client_id': os.getenv('GOOGLE_OAUTH_CLIENT_ID'),
            'secret': os.getenv('GOOGLE_OAUTH_CLIENT_SECRET'),
            'key': ''
        }
    }
}
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = '/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Nairobi')
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(PROJECT_ROOT_DIR, 'frontend', 'static')]
STATIC_ROOT = os.path.join(PROJECT_ROOT_DIR, 'staticfiles_collected')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'mediafiles_storage')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework.authentication.SessionAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticatedOrReadOnly',),
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer', ('rest_framework.renderers.BrowsableAPIRenderer' if DEBUG else None),),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': int(os.getenv('APP_DEFAULT_RESULTS_PER_PAGE', 9)),
    'PAGE_SIZE_QUERY_PARAM': 'page_size',
    'MAX_PAGE_SIZE': 100,
}

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'django-db')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_RESULT_EXTENDED = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

CELERY_TASK_QUEUES = {
    'default': {'exchange': 'default', 'routing_key': 'default'},
    'ai_processing': {'exchange': 'ai_processing', 'routing_key': 'ai_processing'},
    'video_editing': {'exchange': 'video_editing', 'routing_key': 'video_editing'},
}
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_DEFAULT_EXCHANGE = 'default'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'default'
CELERY_TASK_ROUTES = {
    'api.tasks.process_search_query_task': {'queue': 'ai_processing'},
    'api.tasks.process_video_edit_task': {'queue': 'video_editing'},
}

RATELIMIT_ENABLE = os.getenv('DJANGO_RATELIMIT_ENABLE', 'True') == 'True'
RATELIMIT_USE_CACHE = 'default'
RATELIMIT_KEY_PREFIX = 'rl'
RATELIMIT_VIEW = 'django_ratelimit.exceptions.ratelimited'
RATELIMIT_BLOCK = True
RATELIMIT_GLOBAL_DEFAULT_RATE = os.getenv('DJANGO_RATELIMIT_GLOBAL_DEFAULT_RATE', '1000/h')

def user_or_ip_key(group, request):
    if request.user.is_authenticated: return f"user:{request.user.pk}"
    return f"ip:{request.META.get('REMOTE_ADDR')}"
def ip_key(group, request): return request.META.get('REMOTE_ADDR')

RATELIMIT_DEFAULTS = {
    'api_search_initiate': os.getenv('RATELIMIT_API_SEARCH_INITIATE', '20/m'),
    'api_edit_task_create': os.getenv('RATELIMIT_API_EDIT_TASK_CREATE', '10/h'),
    'api_general_read': os.getenv('RATELIMIT_API_GENERAL_READ', '300/m'),
    'auth_actions': os.getenv('RATELIMIT_AUTH_ACTIONS', '30/m'),
    'payments_initiate': os.getenv('RATELIMIT_PAYMENTS_INITIATE', '10/h'),
    'paystack_webhook': os.getenv('RATELIMIT_PAYSTACK_WEBHOOK', '60/m'),
}
RATELIMIT_KEYS = {
    'api_search_initiate': user_or_ip_key,
    'api_edit_task_create': user_or_ip_key,
    'api_general_read': ip_key,
    'auth_actions': ip_key,
    'payments_initiate': user_or_ip_key,
    'paystack_webhook': ip_key,
}

CORS_ALLOW_CREDENTIALS = True
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS_STRING = os.getenv('CORS_ALLOWED_ORIGINS')
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STRING.split(',') if origin.strip()] if CORS_ALLOWED_ORIGINS_STRING else []

LOGGING_DIR = BASE_DIR / 'logs'
LOGGING_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '{levelname} {asctime} {module}:{lineno} {process:d} {thread:d} {message}', 'style': '{'},
                   'simple': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
                 'file_django': {'level': 'INFO', 'class': 'logging.handlers.RotatingFileHandler', 'filename': LOGGING_DIR / 'django.log', 'maxBytes': 10485760, 'backupCount': 5, 'formatter': 'verbose'},
                 'file_papri_app': {'level': 'DEBUG', 'class': 'logging.handlers.RotatingFileHandler', 'filename': LOGGING_DIR / 'papri_app.log', 'maxBytes': 10485760, 'backupCount': 5, 'formatter': 'verbose'}},
    'root': {'handlers': ['console', 'file_django'], 'level': os.getenv('DJANGO_LOG_LEVEL_ROOT', 'WARNING')},
    'loggers': {'django': {'handlers': ['console', 'file_django'], 'level': os.getenv('DJANGO_LOG_LEVEL_DJANGO', 'INFO'), 'propagate': False},
                'api': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
                'ai_agents': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
                'payments': {'handlers': ['console', 'file_papri_app'], 'level': 'DEBUG', 'propagate': False},
                'celery': {'handlers': ['console', 'file_papri_app'], 'level': 'INFO', 'propagate': False}}
}

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
VIMEO_CLIENT_ID = os.getenv('VIMEO_CLIENT_ID')
VIMEO_CLIENT_SECRET = os.getenv('VIMEO_CLIENT_SECRET')
VIMEO_ACCESS_TOKEN = os.getenv('VIMEO_ACCESS_TOKEN')
DAILYMOTION_API_URL = os.getenv('DAILYMOTION_API_URL', 'https://api.dailymotion.com')
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY')
PAYSTACK_WEBHOOK_SECRET = os.getenv('PAYSTACK_WEBHOOK_SECRET')
PAYSTACK_CALLBACK_URL_NAME = 'payments:paystack_callback'
PAYMENT_SUCCESS_REDIRECT_URL = os.getenv('PAYMENT_SUCCESS_REDIRECT_URL', '/app/#payment-success')
PAYMENT_FAILED_REDIRECT_URL = os.getenv('PAYMENT_FAILED_REDIRECT_URL', '/app/#payment-failed')
SIGNUP_CODE_EXPIRY_DAYS = int(os.getenv('SIGNUP_CODE_EXPIRY_DAYS', 7))
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))
QDRANT_GRPC_PORT = int(os.getenv('QDRANT_GRPC_PORT', 6334))
QDRANT_URL = os.getenv('QDRANT_URL', f"http://{QDRANT_HOST}:{QDRANT_PORT}")
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', None)
QDRANT_PREFER_GRPC = os.getenv('QDRANT_PREFER_GRPC', 'False') == 'True'
QDRANT_TIMEOUT_SECONDS = int(os.getenv('QDRANT_TIMEOUT_SECONDS', 20))
QDRANT_TRANSCRIPT_COLLECTION_NAME = os.getenv('QDRANT_TRANSCRIPT_COLLECTION_NAME', 'papri_transcripts_v1')
QDRANT_VISUAL_COLLECTION_NAME = os.getenv('QDRANT_VISUAL_COLLECTION_NAME', 'papri_visuals_v1')
TEXT_EMBEDDING_DIMENSION = int(os.getenv('TEXT_EMBEDDING_DIMENSION', 384))
IMAGE_EMBEDDING_DIMENSION = int(os.getenv('IMAGE_EMBEDDING_DIMENSION', 1280))
SENTENCE_TRANSFORMER_MODEL = os.getenv('SENTENCE_TRANSFORMER_MODEL', 'all-MiniLM-L6-v2')
VISUAL_CNN_MODEL_NAME = os.getenv('VISUAL_CNN_MODEL_NAME', 'EfficientNetV2S')
SPACY_MODEL_NAME = os.getenv('SPACY_MODEL_NAME', "en_core_web_sm")
MOVIEPY_THREADS = int(os.getenv('MOVIEPY_THREADS', 4))
MOVIEPY_PRESET = os.getenv('MOVIEPY_PRESET', 'medium')
PYSCENEDETECT_THRESHOLD = float(os.getenv('PYSCENEDETECT_THRESHOLD', 27.0))
PYSCENEDETECT_MIN_SCENE_LEN = int(os.getenv('PYSCENEDETECT_MIN_SCENE_LEN', 15)) # ADDED

MAX_API_RESULTS_PER_SOURCE = int(os.getenv('MAX_API_RESULTS_PER_SOURCE', 10))
MAX_SCRAPED_ITEMS_PER_SOURCE = int(os.getenv('MAX_SCRAPED_ITEMS_PER_SOURCE', 5))
SCRAPE_INTER_PLATFORM_DELAY_SECONDS = int(os.getenv('SCRAPE_INTER_PLATFORM_DELAY_SECONDS', 2))

try:
    SCRAPEABLE_PLATFORMS_JSON = os.getenv('SCRAPEABLE_PLATFORMS_JSON', '[]')
    SCRAPEABLE_PLATFORMS_CONFIG = json.loads(SCRAPEABLE_PLATFORMS_JSON)
except json.JSONDecodeError:
    SCRAPEABLE_PLATFORMS_CONFIG = []
    if DEBUG:
        SCRAPEABLE_PLATFORMS_CONFIG.append({'name': 'PeerTube_Tilvids_Dev_Example', 'spider_name': 'peertube', 'base_url': 'https://tilvids.com', 'search_path_template': '/api/v1/search/videos?search={query}&count={max_results}&sort=-match', 'default_listing_url': 'https://tilvids.com/videos/recently-added', 'is_active': True, 'platform_identifier': 'peertube_tilvids'})
        print("Warning: SCRAPEABLE_PLATFORMS_JSON not found or invalid. Using default dev config.")

# --- BEGIN: Scraping Robustness Settings ---
USER_AGENT_LIST_JSON = os.getenv('USER_AGENT_LIST_JSON', '["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"]')
try:
    USER_AGENT_LIST = json.loads(USER_AGENT_LIST_JSON)
except json.JSONDecodeError:
    USER_AGENT_LIST = ["PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)"] # Fallback
DEFAULT_USER_AGENT = os.getenv('DEFAULT_USER_AGENT', USER_AGENT_LIST[0] if USER_AGENT_LIST else "PapriSearchBot/1.0")

HTTP_PROXY = os.getenv('HTTP_PROXY', None)
HTTPS_PROXY = os.getenv('HTTPS_PROXY', None)
PROXY_LIST_JSON = os.getenv('PROXY_LIST_JSON', '[]')
try:
    PROXY_LIST = json.loads(PROXY_LIST_JSON)
except json.JSONDecodeError:
    PROXY_LIST = []

SCRAPY_SPIDER_TIMEOUT = int(os.getenv('SCRAPY_SPIDER_TIMEOUT', 300)) # Timeout for Scrapy spider subprocess
SCRAPY_DOWNLOAD_TIMEOUT = int(os.getenv('SCRAPY_DOWNLOAD_TIMEOUT', 30)) # Timeout for individual Scrapy HTTP requests
SCRAPY_DOWNLOAD_DELAY = float(os.getenv('SCRAPY_DOWNLOAD_DELAY', 0.75)) # Base download delay for Scrapy
SCRAPY_CONCURRENT_REQUESTS_PER_DOMAIN = int(os.getenv('SCRAPY_CONCURRENT_REQUESTS_PER_DOMAIN', 4))
# --- END: Scraping Robustness Settings ---

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Papri Support <noreply@yourpaprisite.com>')
ACCOUNT_EMAIL_SUBJECT_PREFIX = '[Papri] '

PAPRI_BASE_URL = os.getenv('PAPRI_BASE_URL', 'http://localhost:80
