# backend/ai_agents/scrapers/settings.py
import os
import json
# Attempt to load Django settings
try:
    from django.conf import settings as django_settings
    DJANGO_SETTINGS_LOADED = True
except ImportError:
    django_settings = None
    DJANGO_SETTINGS_LOADED = False
    print("Scrapy Project Settings: Could not import Django settings. Will use Scrapy defaults or direct env vars.")

BOT_NAME = 'papri_scrapers'
SPIDER_MODULES = ['ai_agents.scrapers.spiders']
NEWSPIDER_MODULE = 'ai_agents.scrapers.spiders'

ROBOTSTXT_OBEY = True

# --- Papri Specific Settings Integration ---
if DJANGO_SETTINGS_LOADED:
    USER_AGENT = getattr(django_settings, 'DEFAULT_USER_AGENT', 'PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)')
    USER_AGENT_LIST_FROM_DJANGO = getattr(django_settings, 'USER_AGENT_LIST', [])
    HTTP_PROXY_FROM_DJANGO = getattr(django_settings, 'HTTP_PROXY', None)
    HTTPS_PROXY_FROM_DJANGO = getattr(django_settings, 'HTTPS_PROXY', None) # Specific for HTTPS
    PROXY_LIST_FROM_DJANGO = getattr(django_settings, 'PROXY_LIST', [])
    DOWNLOAD_TIMEOUT = getattr(django_settings, 'SCRAPY_DOWNLOAD_TIMEOUT', 30)
    DOWNLOAD_DELAY = getattr(django_settings, 'SCRAPY_DOWNLOAD_DELAY', 0.75)
    CONCURRENT_REQUESTS_PER_DOMAIN = getattr(django_settings, 'SCRAPY_CONCURRENT_REQUESTS_PER_DOMAIN', 4)
    CLOSESPIDER_ITEMCOUNT = getattr(django_settings, 'MAX_SCRAPED_ITEMS_PER_SOURCE', 50)
else: # Fallbacks if Django settings not loaded
    USER_AGENT = os.getenv('SCRAPY_DEFAULT_USER_AGENT', 'PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)')
    try: USER_AGENT_LIST_FROM_DJANGO = json.loads(os.getenv('USER_AGENT_LIST_JSON', '[]'))
    except json.JSONDecodeError: USER_AGENT_LIST_FROM_DJANGO = []
    HTTP_PROXY_FROM_DJANGO = os.getenv('HTTP_PROXY', None)
    HTTPS_PROXY_FROM_DJANGO = os.getenv('HTTPS_PROXY', None)
    try: PROXY_LIST_FROM_DJANGO = json.loads(os.getenv('PROXY_LIST_JSON', '[]'))
    except json.JSONDecodeError: PROXY_LIST_FROM_DJANGO = []
    DOWNLOAD_TIMEOUT = int(os.getenv('SCRAPY_DOWNLOAD_TIMEOUT', 30))
    DOWNLOAD_DELAY = float(os.getenv('SCRAPY_DOWNLOAD_DELAY', 0.75))
    CONCURRENT_REQUESTS_PER_DOMAIN = int(os.getenv('SCRAPY_CONCURRENT_REQUESTS_PER_DOMAIN', 4))
    CLOSESPIDER_ITEMCOUNT = int(os.getenv('MAX_SCRAPED_ITEMS_PER_SOURCE', 50))


DEFAULT_REQUEST_HEADERS = {
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
}

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = DOWNLOAD_DELAY
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5
AUTOTHROTTLE_DEBUG = False

RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429]

DOWNLOADER_MIDDLEWARES = {
   'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
   'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
   # Enable your custom proxy middleware if you have one and it's configured
   # 'ai_agents.scrapers.middlewares.RotatingProxyMiddleware': 610,
   # Scrapy's built-in HttpProxyMiddleware is ~750, activate by setting http_proxy/https_proxy env vars
   # 'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': 750,
}

if USER_AGENT_LIST_FROM_DJANGO:
    USER_AGENTS = USER_AGENT_LIST_FROM_DJANGO
else:
    USER_AGENTS = [USER_AGENT, "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"] # Fallback

# For custom RotatingProxyMiddleware
if PROXY_LIST_FROM_DJANGO:
    ROTATING_PROXY_LIST = PROXY_LIST_FROM_DJANGO

# If using Scrapy's built-in HttpProxyMiddleware, ensure HTTP_PROXY/HTTPS_PROXY environment variables are set.
# The Django settings HTTP_PROXY and HTTPS_PROXY can be used to set these environment variables
# when the Scrapy process is launched from Django, e.g., in SourceOrchestrationAgent._run_scrapy_spider
if HTTP_PROXY_FROM_DJANGO and 'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware' not in DOWNLOADER_MIDDLEWARES:
     DOWNLOADER_MIDDLEWARES['scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware'] = 750
     # Scrapy's HttpProxyMiddleware picks up http_proxy and https_proxy from os.environ

# ITEM_PIPELINES = {
#    'ai_agents.scrapers.pipelines.SomePipeline': 300,
# }

LOG_LEVEL = 'INFO'
REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
FEED_EXPORT_ENCODING = 'utf-8'
