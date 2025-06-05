# backend/ai_agents/scrapers/spiders/peertube_spider.py
import scrapy
from urllib.parse import urlencode, urljoin, unquote, urlparse
import json
import logging
from datetime import datetime, timezone as dt_timezone
from dateutil import parser as dateutil_parser # For robust date parsing

# Assuming PapriVideoItem is in ..items (relative to this spiders directory)
from ..items import PapriVideoItem

logger = logging.getLogger(__name__)

class PeertubeSpider(scrapy.Spider):
    name = 'peertube'
    # allowed_domains will be set dynamically based on the instance URL in __init__

    # Default custom settings for this spider, can be overridden by project settings
    custom_settings = {
        'ROBOTSTXT_OBEY': True,
        'DOWNLOAD_DELAY': 0.75,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_TARGET_CONCURRENCY': 1.0, # Be very polite
        'RETRY_TIMES': 2,
        'RETRY_HTTP_CODES': [500, 502, 503, 504, 522, 524, 408, 429],
        'DOWNLOAD_TIMEOUT': 20, # Shorter timeout for API calls
        'LOG_LEVEL': 'INFO', # Reduce verbosity for this spider
    }

    def __init__(self, *args, **kwargs):
        super(PeertubeSpider, self).__init__(*args, **kwargs)
        self.target_instance_base_url = kwargs.get('target_instance_base_url')
        self.search_query = kwargs.get('search_query')
        # Default search path template for PeerTube API v1
        self.search_path_template = kwargs.get('search_path_template', '/api/v1/search/videos')
        self.max_results_to_fetch = int(kwargs.get('max_results', 10)) # Total items this spider instance should yield
        self.platform_identifier = kwargs.get('platform_identifier', 'peertube_generic')
        
        # API specific pagination parameters
        self.api_items_per_page = int(kwargs.get('items_per_page_api', self.max_results_to_fetch if self.max_results_to_fetch <= 25 else 25)) # PeerTube API 'count' param
        self.current_api_start_index = int(kwargs.get('start_index_api', 0)) # PeerTube API 'start' param (0-indexed)
        
        self.items_yielded_count = 0 # Counter for items yielded by this spider instance

        if not self.target_instance_base_url:
            raise ValueError("PeertubeSpider requires 'target_instance_base_url' argument.")
        
        try:
            parsed_uri = urlparse(self.target_instance_base_url)
            self.allowed_domains = [parsed_uri.netloc]
        except Exception as e:
            logger.error(f"Invalid target_instance_base_url for PeertubeSpider: {self.target_instance_base_url}. Error: {e}")
            raise ValueError(f"Invalid base URL: {self.target_instance_base_url}")

        logger.info(
            f"PeertubeSpider initialized for instance: {self.target_instance_base_url}, query: '{self.search_query}', "
            f"max_results: {self.max_results_to_fetch}, platform_id: {self.platform_identifier}, "
            f"API items/page: {self.api_items_per_page}, initial API start index: {self.current_api_start_index}"
        )

    def start_requests(self):
        if not self.search_query:
            logger.warning(f"PeertubeSpider: No search query provided for {self.target_instance_base_url}. No requests will be made.")
            return # No query, no search.

        # Construct the initial API search URL
        # PeerTube API v1 common parameters: search, count, start, sort, nsfw, filter
        query_params = {
            'search': self.search_query,
            'count': self.api_items_per_page,
            'start': self.current_api_start_index,
            'sort': '-match',      # Sort by relevance (match score descending)
            'nsfw': 'false',       # Exclude NSFW content by default
            'filter': 'local'      # Search only local videos on the instance by default
        }
        
        # The search_path_template might already include some fixed params or be just the base path
        if '?' in self.search_path_template: # Template likely includes base path and some params
            base_api_path = self.search_path_template
            # We need to carefully merge/override params. For now, assume template is just base path like '/api/v1/search/videos'
            # A more robust way would be to parse params from template and merge.
        else:
            base_api_path = self.search_path_template
            
        # Ensure base_api_path starts with a slash if it's a path
        if not base_api_path.startswith('/'):
            base_api_path = '/' + base_api_path
            
        api_url_with_params = f"{base_api_path}?{urlencode(query_params)}"
        start_url = urljoin(self.target_instance_base_url, api_url_with_params)
        
        logger.info(f"PeertubeSpider: Starting request to: {start_url}")
        yield scrapy.Request(start_url, self.parse_api_response, errback=self.handle_error,
                             meta={'current_api_start_index': self.current_api_start_index})

    def handle_error(self, failure):
        request_url = failure.request.url
        exception_type = failure.type.__name__
        exception_value = str(failure.value)
        logger.error(
            f"Request failed for {request_url} (Spider: {self.name}, Instance: {self.target_instance_base_url}). "
            f"Type: {exception_type}. Value: {exception_value}.",
            exc_info=True # Include traceback for detailed debugging
        )
        # You could yield an error item here if you want to propagate this to pipelines/MainOrchestrator
        # item = PapriVideoItem()
        # item['error_message'] = f"Request failed: {exception_type} - {exception_value} for URL {request_url}"
        # item['platform_name'] = self.platform_identifier
        # item['spider_name'] = self.name
        # yield item

    def parse_api_response(self, response):
        current_api_start_index_for_this_page = response.meta.get('current_api_start_index', 0)
        logger.debug(f"Parsing API response from {response.url} (Start index: {current_api_start_index_for_this_page})")

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from {response.url}. Snippet: {response.text[:250]}", exc_info=True)
            return # Cannot proceed without valid JSON

        videos_on_this_page = data.get('data', [])
        total_videos_on_platform_for_query = data.get('total', 0)

        if not videos_on_this_page:
            logger.info(f"No video data in API response from {response.url}. Total videos on platform for query: {total_videos_on_platform_for_query}")
            return

        for video_data in videos_on_this_page:
            if self.items_yielded_count >= self.max_results_to_fetch:
                logger.info(f"PeertubeSpider: Reached max_results_to_fetch limit of {self.max_results_to_fetch}. Halting.")
                return # Stop yielding more items

            item = PapriVideoItem()
            item['platform_name'] = self.platform_identifier
            item['spider_name'] = self.name
            item['scraped_at_timestamp'] = datetime.now(dt_timezone.utc).isoformat()
            item['title'] = video_data.get('name')
            video_uuid = video_data.get('uuid')

            if video_uuid:
                item['original_url'] = urljoin(self.target_instance_base_url, f"/videos/watch/{video_uuid}")
                item['platform_video_id'] = video_uuid
                item['embed_url'] = urljoin(self.target_instance_base_url, f"/videos/embed/{video_uuid}")
            else:
                logger.warning(f"Missing 'uuid' for video data from {response.url}: {str(video_data)[:150]}. Skipping item.")
                continue # Cannot form a unique ID or URL without UUID
            
            item['description'] = video_data.get('description')
            thumbnail_path = video_data.get('thumbnailPath')
            if thumbnail_path: item['thumbnail_url'] = urljoin(self.target_instance_base_url, thumbnail_path)
            
            if video_data.get('publishedAt'):
                try: item['publication_date_str'] = dateutil_parser.isoparse(video_data['publishedAt']).isoformat()
                except (ValueError, TypeError) as e_date: logger.warning(f"Could not parse publishedAt date '{video_data.get('publishedAt')}' for {item['original_url']}: {e_date}")
            
            duration_s = video_data.get('duration') # In seconds
            if duration_s is not None: item['duration_str'] = str(duration_s)

            if video_data.get('account'):
                item['uploader_name'] = video_data['account'].get('displayName')
                uploader_account_name = video_data['account'].get('name')
                if uploader_account_name: item['uploader_url'] = urljoin(self.target_instance_base_url, f"/a/{uploader_account_name}")
            
            item['view_count_str'] = str(video_data.get('views', 0))
            item['like_count_str'] = str(video_data.get('likes', 0))
            item['comment_count_str'] = str(video_data.get('commentsCount', 0))
            item['tags_list'] = video_data.get('tags', [])
            if video_data.get('category'): item['category_str'] = video_data['category'].get('label')

            captions = video_data.get('captions', [])
            if captions:
                en_caption = next((c for c in captions if c.get('language', {}).get('id') == 'en'), None)
                if en_caption and en_caption.get('captionPath'):
                    item['transcript_vtt_url'] = urljoin(self.target_instance_base_url, en_caption['captionPath'])
                elif captions[0].get('captionPath'): # Fallback to first caption
                     item['transcript_vtt_url'] = urljoin(self.target_instance_base_url, captions[0]['captionPath'])
            
            self.items_yielded_count += 1
            yield item

        # Pagination: Check if more results are available and needed
        next_start_index = current_api_start_index_for_this_page + len(videos_on_this_page)
        if videos_on_this_page and next_start_index < total_videos_on_platform_for_query and self.items_yielded_count < self.max_results_to_fetch:
            logger.info(f"PeertubeSpider: Requesting next page. New start index: {next_start_index}")
            
            query_params_next_page = {
                'search': self.search_query, 'count': self.api_items_per_page, 'start': next_start_index,
                'sort': '-match', 'nsfw': 'false', 'filter': 'local'
            }
            if '?' in self.search_path_template: base_api_path = self.search_path_template
            else: base_api_path = self.search_path_template
            if not base_api_path.startswith('/'): base_api_path = '/' + base_api_path
            
            next_page_api_url_with_params = f"{base_api_path}?{urlencode(query_params_next_page)}"
            next_page_url = urljoin(self.target_instance_base_url, next_page_api_url_with_params)
            
            yield scrapy.Request(next_page_url, self.parse_api_response, errback=self.handle_error,
                                 meta={'current_api_start_index': next_start_index})
        else:
            logger.info(f"PeertubeSpider: No more pages to fetch or max_results reached for {self.target_instance_base_url}. Total yielded: {self.items_yielded_count}")
