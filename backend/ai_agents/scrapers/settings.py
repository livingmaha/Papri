# backend/ai_agents/scrapers/settings.py

# Scrapy settings for papri_scrapers project
#
# For simplicity, we'll keep this minimal.
# When running Scrapy spiders via Django (e.g., through a management command or Celery task),
# you might inject Django settings or use environment variables.

BOT_NAME = 'papri_scrapers'

SPIDER_MODULES = ['ai_agents.scrapers.spiders']
NEWSPIDER_MODULE = 'ai_agents.scrapers.spiders'


# Obey robots.txt rules
ROBOTSTXT_OBEY = True # Be a good internet citizen

# Configure maximum concurrent requests performed by Scrapy (default: 16)
# CONCURRENT_REQUESTS = 16

# Configure a delay for requests for the same website (default: 0)
# See https://docs.scrapy.org/en/latest/topics/settings.html#download-delay
# DOWNLOAD_DELAY = 1 # 1 second delay can be polite
# The download delay setting will honor only one of:
# CONCURRENT_REQUESTS_PER_DOMAIN = 8 # Default is 8
# CONCURRENT_REQUESTS_PER_IP = 0 # Default is 0 (disabled)

# Disable cookies (enabled by default)
# COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
# TELNETCONSOLE_ENABLED = False

# Override the default request headers:
DEFAULT_REQUEST_HEADERS = {
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9', # Prefer English content
  # 'User-Agent': 'PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)', # Set a custom User-Agent
}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
# SPIDER_MIDDLEWARES = {
#    'papri_scrapers.middlewares.PapriScrapersSpiderMiddleware': 543,
# }

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/settings.html#downloader-middlewares
# DOWNLOADER_MIDDLEWARES = {
#    'papri_scrapers.middlewares.PapriScrapersDownloaderMiddleware': 543,
#    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None, # Disable default Scrapy UA
#    'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400, # If using scrapy-user-agents
# }

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
# EXTENSIONS = {
#    'scrapy.extensions.telnet.TelnetConsole': None,
# }

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
# ITEM_PIPELINES = {
#    'ai_agents.scrapers.pipelines.PapriScrapersPipeline': 300,
#    # Example: a pipeline to save to JSON file for debugging
#    # 'ai_agents.scrapers.pipelines.JsonWriterPipeline': 800,
# }

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
# AUTOTHROTTLE_ENABLED = True
# The initial download delay
# AUTOTHROTTLE_START_DELAY = 5
# The maximum download delay to be set in case of high latencies
# AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
# AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Enable showing throttling stats for every response received:
# AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
# HTTPCACHE_ENABLED = True
# HTTPCACHE_EXPIRATION_SECS = 0 # Never expire
# HTTPCACHE_DIR = 'httpcache'
# HTTPCACHE_IGNORE_HTTP_CODES = []
# HTTPCACHE_STORAGE = 'scrapy.extensions.httpcache.FilesystemCacheStorage'

# Set settings whose default value is deprecated to a future-proof value
REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor' # For Scrapy 2.6+
FEED_EXPORT_ENCODING = 'utf-8'

# Custom settings for Papri
# These could be loaded from Django settings or environment variables when spiders run.
# For example, in your Django settings.py:
# SCRAPER_USER_AGENT = "PapriSearchBot/1.0 (+http://yourpaprisite.com/bot-info)"
# And then in spider: from django.conf import settings; user_agent = settings.SCRAPER_USER_AGENT

# LOG_LEVEL = 'INFO' # Default is DEBUG, can be noisy
# LOG_FILE = 'scrapy_log.txt' # If you want to log to a file

# For Selenium/Playwright integration (if needed for dynamic sites)
# These would require additional setup in middlewares.
# from shutil import which
# SELENIUM_DRIVER_NAME = 'chrome'
# SELENIUM_DRIVER_EXECUTABLE_PATH = which('chromedriver')
# SELENIUM_DRIVER_ARGUMENTS=['--headless'] # Or other options

# PLAYWRIGHT_BROWSER_TYPE = 'chromium'
# PLAYWRIGHT_LAUNCH_OPTIONS = {'headless': True}

# Max items to scrape per spider run (can be overridden by spider arguments)
CLOSESPIDER_ITEMCOUNT = 100 # Default limit if not set by caller
