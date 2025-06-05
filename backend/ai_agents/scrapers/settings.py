# backend/ai_agents/scrapers/scrapers/settings.py (or your Scrapy project's settings path)

# Scrapy settings for papri_scrapers project
BOT_NAME = 'papri_scrapers'

SPIDER_MODULES = ['ai_agents.scrapers.spiders'] # Ensure this path is correct relative to Scrapy project root
NEWSPIDER_MODULE = 'ai_agents.scrapers.spiders' # Ensure this path is correct

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# --- PAPRI CUSTOMIZATIONS ---
# Attempt to load Django settings to get USER_AGENT_LIST, PROXY_LIST etc.
# This requires the Scrapy process to have Django environment configured.
# This is typically handled when running spiders via Django management commands or Celery tasks.
DJANGO_SETTINGS_MODULE = os.environ.get('DJANGO_SETTINGS_MODULE', 'papri_project.settings')
try:
    from django.conf import settings as django_settings
    # User-Agent Settings
    USER_AGENT = getattr(django_settings, 'DEFAULT_USER_AGENT', 'PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)')
    USER_AGENT_LIST_FROM_DJANGO = getattr(django_settings, 'USER_AGENT_LIST', None)
    
    # Proxy Settings
    HTTP_PROXY_FROM_DJANGO = getattr(django_settings, 'HTTP_PROXY', None)
    HTTPS_PROXY_FROM_DJANGO = getattr(django_settings, 'HTTPS_PROXY', None)
    PROXY_LIST_FROM_DJANGO = getattr(django_settings, 'PROXY_LIST', None)
    
    # Configure download timeout (example)
    DOWNLOAD_TIMEOUT = getattr(django_settings, 'SCRAPY_DOWNLOAD_TIMEOUT', 30) # Default to 30s

except ImportError:
    print("Scrapy Project Settings: Could not import Django settings. Using Scrapy defaults or .env variables directly if configured.")
    USER_AGENT = os.getenv('SCRAPY_DEFAULT_USER_AGENT', 'PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)')
    USER_AGENT_LIST_FROM_DJANGO = json.loads(os.getenv('USER_AGENT_LIST_JSON', '[]'))
    HTTP_PROXY_FROM_DJANGO = os.getenv('HTTP_PROXY', None)
    PROXY_LIST_FROM_DJANGO = json.loads(os.getenv('PROXY_LIST_JSON', '[]'))
    DOWNLOAD_TIMEOUT = int(os.getenv('SCRAPY_DOWNLOAD_TIMEOUT', 30))


# Default request headers
DEFAULT_REQUEST_HEADERS = {
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
  # User-Agent will be set by UserAgentMiddleware or RandomUserAgentMiddleware if enabled
}

# Configure a delay for requests for the same website (default: 0)
DOWNLOAD_DELAY = 1 # Start with 1 second delay, AutoThrottle can adjust
CONCURRENT_REQUESTS_PER_DOMAIN = 4 # Limit concurrency

# Enable and configure AutoThrottle
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1 # Initial download delay
AUTOTHROTTLE_MAX_DELAY = 30  # Max download delay
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5 # Aim for this many concurrent requests per domain on average
AUTOTHROTTLE_DEBUG = False # Set to True to see throttling stats

# Retry Middleware Settings (enabled by default, but can be configured)
RETRY_ENABLED = True
RETRY_TIMES = 3 # Retry failed requests 3 times
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429] # HTTP codes to retry
# For more robust retry, consider scrapy-retry-policies or custom retry logic.

# Downloader Middlewares
DOWNLOADER_MIDDLEWARES = {
   # 'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': 110, # For basic proxy
   # 'ai_agents.scrapers.middlewares.RotatingProxyMiddleware': 610, # If you implement a custom one
   'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None, # Disable default Scrapy UA
   # Using scrapy-user-agents for random user agent rotation:
   'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
}

# Pass the list of user agents to scrapy-user-agents (if USER_AGENT_LIST_FROM_DJANGO is populated)
if USER_AGENT_LIST_FROM_DJANGO:
    USER_AGENTS = USER_AGENT_LIST_FROM_DJANGO
else: # Fallback if Django settings not loaded or list is empty
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Version/14.1.1 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0",
        USER_AGENT # Include the default one
    ]


# If using a single proxy from Django settings:
# Ensure HttpProxyMiddleware is enabled (it usually is by default if http_proxy env var is set by Scrapy)
# And set HTTP_PROXY / HTTPS_PROXY environment variables before running Scrapy,
# or configure them directly if your custom proxy middleware needs it.
# if HTTP_PROXY_FROM_DJANGO:
#     # This setup is more for when Scrapy runs standalone and picks up env vars.
#     # If run via Django, ensure these env vars are available to the Scrapy process.
#     os.environ['HTTP_PROXY'] = HTTP_PROXY_FROM_DJANGO
#     os.environ['HTTPS_PROXY'] = HTTPS_PROXY_FROM_DJANGO if HTTPS_PROXY_FROM_DJANGO else HTTP_PROXY_FROM_DJANGO

# If using a proxy list for a custom rotating proxy middleware,
# you'd pass PROXY_LIST_FROM_DJANGO to that middleware's settings.
# Example custom setting for a hypothetical RotatingProxyMiddleware:
# ROTATING_PROXY_LIST = PROXY_LIST_FROM_DJANGO


# Configure item pipelines
# ITEM_PIPELINES = {
#    'ai_agents.scrapers.pipelines.ValidationPipeline': 300,
#    'ai_agents.scrapers.pipelines.JsonLinesWriterPipeline': 800, # If outputting to file directly
# }

# Max items to scrape per spider run (can be overridden by spider arguments or spider logic)
CLOSESPIDER_ITEMCOUNT = getattr(settings, 'MAX_SCRAPED_ITEMS_PER_SOURCE', 50)

# Logging
LOG_LEVEL = 'INFO'
# LOG_FILE = 'scrapy_papri.log' # Define if you want file-based logging from Scrapy

# Ensure compatibility for Scrapy 2.6+
REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
FEED_EXPORT_ENCODING = 'utf-8'
