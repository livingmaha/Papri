# backend/ai_agents/scrapers/scrapers/middlewares.py (or your Scrapy project's middlewares path)
import logging
import random
from urllib.parse import urlparse

# from scrapy.exceptions import NotConfigured # If you want to disable middleware if not configured
# from django.conf import settings as django_settings # If loading proxies from Django settings

logger = logging.getLogger(__name__)

class CustomHttpHeadersMiddleware:
    """This middleware allows spiders to pass custom headers."""
    def process_request(self, request, spider):
        if hasattr(spider, 'custom_headers') and isinstance(spider.custom_headers, dict):
            for header, value in spider.custom_headers.items():
                request.headers.setdefault(header, value)
        return None


class RotatingProxyMiddleware:
    """
    A simple rotating proxy middleware.
    Enable this in your Scrapy project settings (DOWNLOADER_MIDDLEWARES)
    and provide PROXY_LIST in Scrapy settings (can be loaded from Django settings).
    """
    def __init__(self, proxies):
        self.proxies = proxies
        if not self.proxies:
            logger.warning("RotatingProxyMiddleware enabled, but no proxies provided in PROXY_LIST.")
            # raise NotConfigured("No proxies provided for RotatingProxyMiddleware.")


    @classmethod
    def from_crawler(cls, crawler):
        # Get proxies from Scrapy settings (which might have loaded them from Django settings)
        proxies = crawler.settings.getlist('PROXY_LIST', []) 
        # If PROXY_LIST_FROM_DJANGO was set directly in Scrapy settings:
        # proxies = crawler.settings.get('PROXY_LIST_FROM_DJANGO', [])
        return cls(proxies)

    def process_request(self, request, spider):
        if not self.proxies or 'proxy' in request.meta: # Don't override if proxy already set
            return

        # Only apply proxy to http/https requests
        if not request.url.startswith("http"):
            return

        proxy_address = random.choice(self.proxies)
        request.meta['proxy'] = proxy_address
        logger.debug(f"Using proxy <{proxy_address}> for request <{request.url}>")
        
        # If your proxies require authentication (e.g., user:pass@host:port)
        # you might need to set request.headers['Proxy-Authorization']
        # based on the proxy_address format.
        # For example:
        # from scrapy.utils.python import to_bytes
        # from w3lib.http import basic_auth_header
        # parsed_proxy = urlparse(proxy_address)
        # if parsed_proxy.username and parsed_proxy.password:
        #     user_pass = to_bytes(f"{unquote(parsed_proxy.username)}:{unquote(parsed_proxy.password)}")
        #     request.headers['Proxy-Authorization'] = basic_auth_header(user_pass)
        
        return None

    def process_exception(self, request, exception, spider):
        # Called when a download handler or a process_request() middleware raises an exception.
        proxy = request.meta.get('proxy')
        logger.warning(f"Request through proxy <{proxy}> failed: <{request.url}>, Exception: <{exception}>")
        # Here you could implement logic to ban a proxy if it fails too often.
        return None # Return None to let Scrapy's default exception handling proceed
