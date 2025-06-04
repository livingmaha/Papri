# backend/ai_agents/scrapers/spiders/peertube_spider.py
import scrapy
from urllib.parse import urlencode, urljoin, unquote
import json
import logging
from datetime import datetime

from ..items import PapriVideoItem # Relative import for items

logger = logging.getLogger(__name__)

class PeertubeSpider(scrapy.Spider):
    name = 'peertube'
    # allowed_domains will be set dynamically based on the instance URL
    # start_urls will also be set dynamically

    custom_settings = {
        'ROBOTSTXT_OBEY': True, # Usually good to obey
        'DOWNLOAD_DELAY': 0.5,   # Be polite to PeerTube instances
        'CONCURRENT_REQUESTS_PER_DOMAIN': 4, # Limit concurrency
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_TARGET_CONCURRENCY': 2.0,
    }

    def __init__(self, *args, **kwargs):
        super(PeertubeSpider, self).__init__(*args, **kwargs)
        
        # These will be passed from SOIAgent when running the spider
        self.target_instance_base_url = kwargs.get('target_instance_base_url') # e.g., "https://tilvids.com"
        self.search_query = kwargs.get('search_query') # The user's query text
        self.search_path_template = kwargs.get('search_path_template', '/api/v1/search/videos?search={query}') # API path
        self.max_results = int(kwargs.get('max_results', 10)) # Max results to fetch for this query
        self.platform_identifier = kwargs.get('platform_identifier', 'peertube_generic') # e.g., 'peertube_tilvids'

        if not self.target_instance_base_url:
            raise ValueError("PeertubeSpider requires 'target_instance_base_url' argument.")
        
        self.allowed_domains = [urlparse(self.target_instance_base_url).netloc]
        
        if self.search_query:
            # Construct search URL using PeerTube API (preferred over HTML scraping if available)
            # Example API endpoint: /api/v1/search/videos?search=myquery
            # Some instances might use /search/videos?search=myquery (HTML)
            if '{query}' in self.search_path_template:
                search_path = self.search_path_template.format(query=urlencode({'search': self.search_query})[7:]) # Crude way to get just encoded query
                # A better way for API query construction:
                encoded_query = urlencode({'search': self.search_query}) # search=...
                api_search_path = f"/api/v1/search/videos?{encoded_query}&count={self.max_results}&sort=-match" # Example API call
                self.start_urls = [urljoin(self.target_instance_base_url, api_search_path)]
            else: # Fallback if template is just a base search page
                logger.warning(f"search_path_template for {self.target_instance_base_url} does not contain {{query}}. Search may be less effective.")
                self.start_urls = [urljoin(self.target_instance_base_url, self.search_path_template)]
        else:
            # If no search query, maybe fetch from a default listing URL (passed as start_urls by SOIAgent)
            self.start_urls = kwargs.get('start_urls', [])
            if not self.start_urls:
                 default_listing = kwargs.get('default_listing_url')
                 if default_listing:
                    self.start_urls = [default_listing]
                 else: # Fallback to a generic videos page if nothing else
                    self.start_urls = [urljoin(self.target_instance_base_url, '/videos/recently-added')]


        logger.info(f"PeertubeSpider initialized for instance: {self.target_instance_base_url}, query: '{self.search_query}', start_urls: {self.start_urls}")
        self.item_count = 0


    def parse(self, response):
        """
        Main parsing method. Handles PeerTube API JSON response for video searches.
        If it's an HTML page (e.g., a listing page), different parsing logic would be needed.
        """
        logger.debug(f"Parsing response from {response.url} for PeerTube instance {self.target_instance_base_url}")

        try:
            # Assuming the response is JSON from PeerTube's search API
            data = json.loads(response.text)
            videos = data.get('data', [])
            
            if not videos:
                logger.info(f"No video data found in JSON response from {response.url}. Total items in response: {data.get('total')}")
                if not data.get('total',0) > 0 and not data.get('data'): # Check if it's an HTML page instead
                    logger.warning(f"Response from {response.url} might not be JSON. Attempting HTML parse as fallback (not implemented yet).")
                    # yield from self.parse_html_listing(response) # Implement this if needed
                return

            for video_data in videos:
                if self.item_count >= self.max_results:
                    logger.info(f"Reached max_results limit of {self.max_results} for PeerTube spider.")
                    return

                item = PapriVideoItem()
                item['platform_name'] = self.platform_identifier
                item['spider_name'] = self.name
                item['scraped_at_timestamp'] = datetime.utcnow().isoformat()

                item['title'] = video_data.get('name')
                # PeerTube video URL usually looks like: {instance_base_url}/w/{uuid} or /videos/watch/{uuid}
                # The API often provides `uuid`. `url` field might be the API URL.
                video_uuid = video_data.get('uuid')
                if video_uuid:
                    item['original_url'] = urljoin(self.target_instance_base_url, f"/videos/watch/{video_uuid}")
                    item['platform_video_id'] = video_uuid
                else: # Fallback if UUID not directly available, try to get from a URL field
                    # This part needs checking against actual PeerTube API response structure
                    direct_url = video_data.get('url') # This might be API URL, not watch URL
                    if direct_url and '/api/v1/videos/' in direct_url : # Heuristic
                        item['original_url'] = direct_url.replace('/api/v1/videos/', '/videos/watch/') # Guess watch URL
                        item['platform_video_id'] = direct_url.split('/')[-1]
                    elif direct_url:
                         item['original_url'] = direct_url # Assume it's the watch URL
                         # Try to extract ID if possible (highly dependent on URL structure)
                         try:
                            item['platform_video_id'] = urlparse(direct_url).path.split('/')[-1]
                         except: pass


                item['description'] = video_data.get('description') or video_data.get('comments') # Some APIs use 'comments' for desc
                
                # Thumbnails: PeerTube API provides various thumbnail paths
                # e.g., thumbnailPath, previewPath. Construct full URL.
                thumbnail_path = video_data.get('thumbnailPath')
                if thumbnail_path:
                    item['thumbnail_url'] = urljoin(self.target_instance_base_url, thumbnail_path)
                
                item['publication_date_str'] = video_data.get('publishedAt') # ISO format string
                
                duration_seconds = video_data.get('duration') # Usually in seconds
                if duration_seconds is not None:
                    item['duration_str'] = str(duration_seconds) # Store as string, SOIAgent will parse to int

                if video_data.get('account'):
                    item['uploader_name'] = video_data['account'].get('displayName')
                    # Construct uploader URL: {instance_base_url}/a/{account_name}
                    uploader_account_name = video_data['account'].get('name')
                    if uploader_account_name:
                        item['uploader_url'] = urljoin(self.target_instance_base_url, f"/a/{uploader_account_name}")
                
                item['view_count_str'] = str(video_data.get('views', 0))
                item['like_count_str'] = str(video_data.get('likes', 0))
                # comment_count might be in `video_data.get('commentsCount')`
                item['comment_count_str'] = str(video_data.get('commentsCount',0))

                item['tags_list'] = video_data.get('tags', [])
                if video_data.get('category'):
                    item['category_str'] = video_data['category'].get('label')
                
                # Embed URL: /videos/embed/{uuid}
                if video_uuid:
                    item['embed_url'] = urljoin(self.target_instance_base_url, f"/videos/embed/{video_uuid}")

                # Transcript handling (PeerTube API might provide captions)
                captions = video_data.get('captions', [])
                if captions:
                    # Prefer English or first available VTT
                    # This is a simplification; robust transcript fetching would check language codes
                    # and potentially download and parse VTT files.
                    # For now, let's assume we can find a direct VTT URL or text.
                    # Example: caption object: {'captionPath': '/static/.../en.vtt', 'language': {'id': 'en', 'label': 'English'}}
                    en_caption_path = next((cap.get('captionPath') for cap in captions if cap.get('language',{}).get('id') == 'en'), None)
                    if en_caption_path:
                        item['transcript_vtt_url'] = urljoin(self.target_instance_base_url, en_caption_path)
                    elif captions[0].get('captionPath'): # Fallback to first caption
                        item['transcript_vtt_url'] = urljoin(self.target_instance_base_url, captions[0].get('captionPath'))
                
                if item.get('title') and item.get('original_url'): # Basic validation
                    self.item_count += 1
                    yield item
                else:
                    logger.warning(f"Skipping item due to missing title or original_url: {video_data}")


            # Handle pagination if the API supports it (e.g., using 'start' and 'count' parameters)
            # PeerTube API uses `total` and current `data` length. If more items, construct next page URL.
            # Example: /api/v1/search/videos?search=...&start=10&count=10
            # This part requires careful inspection of the specific PeerTube instance's API behavior.
            # For now, this spider fetches one page based on `max_results` via `count` param.
            # If `data.get('total')` is greater than `len(videos)` and `len(videos)` == `self.max_results_per_page_from_api`,
            # you would construct the next API call URL.

        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from {response.url}. Content snippet: {response.text[:200]}")
            # Potentially try parsing as HTML if this is a common fallback
            # yield from self.parse_html_listing(response)
        except Exception as e:
            logger.error(f"Error parsing PeerTube response from {response.url}: {e}", exc_info=True)

    # def parse_html_listing(self, response):
    #     """Fallback parser for HTML listing pages if API fails or is not used."""
    #     logger.info(f"Attempting HTML parsing for {response.url} (Not fully implemented in this example)")
    #     # Use Scrapy CSS selectors or XPath to extract video information
    #     # Example (highly dependent on PeerTube theme HTML structure):
    #     # for video_card in response.css('div.video-card-class'): # Replace with actual selectors
    #     #     item = PapriVideoItem()
    #     #     item['title'] = video_card.css('a.title-class::text').get()
    #     #     item['original_url'] = response.urljoin(video_card.css('a.title-class::attr(href)').get())
    #     #     # ... extract other fields ...
    #     #     if item.get('title') and item.get('original_url'):
    #     #          self.item_count += 1
    #     #          if self.item_count > self.max_results: return
    #     #          yield item
    #     pass
