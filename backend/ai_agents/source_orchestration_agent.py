# backend/ai_agents/source_orchestration_agent.py
import logging
import requests # For direct API calls (YouTube, Vimeo, Dailymotion)
import json
import os
import subprocess # For running Scrapy spiders
import tempfile # For temporary output files from Scrapy
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote_plus
from dateutil import parser as dateutil_parser # For robust date string parsing
import time
import re

from django.conf import settings
# from .scrapers.items import PapriVideoItem # Used conceptually for data structure

# Utility functions from within the agent system
from .utils import get_domain_from_url, make_absolute_url, robust_json_loads

logger = logging.getLogger(__name__)

# Helper function to convert duration strings (ISO 8601, HH:MM:SS) to seconds
def parse_duration_to_seconds(duration_str: str) -> int | None:
    if not duration_str:
        return None
    try:
        # ISO 8601 duration format (e.g., PT1M30S)
        if duration_str.startswith('PT'):
            total_seconds = 0
            # Remove PT prefix
            duration_str = duration_str[2:]
            
            hours_match = re.search(r'(\d+)H', duration_str)
            if hours_match:
                total_seconds += int(hours_match.group(1)) * 3600
            minutes_match = re.search(r'(\d+)M', duration_str)
            if minutes_match:
                total_seconds += int(minutes_match.group(1)) * 60
            seconds_match = re.search(r'(\d+)S', duration_str)
            if seconds_match:
                total_seconds += int(seconds_match.group(1))
            return total_seconds if total_seconds > 0 else None
        
        # HH:MM:SS or MM:SS format
        parts = list(map(int, duration_str.split(':')))
        if len(parts) == 3: # HH:MM:SS
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2: # MM:SS
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1: # SS (seconds only)
            return parts[0]
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Could not parse duration string '{duration_str}': {e}")
    return None


class SourceOrchestrationAgent:
    def __init__(self):
        self.youtube_api_key = settings.YOUTUBE_API_KEY
        self.vimeo_access_token = settings.VIMEO_ACCESS_TOKEN # Or use client_id/secret for OAuth flow
        # Dailymotion: Public data often doesn't require a key, or uses OAuth for user-specific actions.
        # For public search, API calls might be unauthenticated or use a generic API key if provided.
        # self.dailymotion_api_key = settings.DAILYMOTION_API_KEY (if you have one)

        self.max_api_results = getattr(settings, 'MAX_API_RESULTS_PER_SOURCE', 5)
        self.max_scraped_items = getattr(settings, 'MAX_SCRAPED_ITEMS_PER_SOURCE', 3)
        self.scrape_inter_platform_delay = getattr(settings, 'SCRAPE_INTER_PLATFORM_DELAY_SECONDS', 1)
        
        # Path to Scrapy executable (robustly find it)
        # This assumes Scrapy is in PATH. If in a venv, ensure Django runs in same venv.
        self.scrapy_executable = "scrapy" # Or provide full path if necessary
        # Base directory of the Scrapy project (ai_agents/scrapers)
        self.scrapers_project_dir = os.path.join(os.path.dirname(__file__), 'scrapers')

        logger.info("SourceOrchestrationAgent initialized.")

    def _make_api_request(self, url, headers=None, params=None, method='GET'):
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=15)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=params, timeout=15) # Assuming JSON payload for POST
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return None
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"API HTTP error for {url}: {http_err}. Response: {http_err.response.text[:200]}", exc_info=True)
        except requests.exceptions.RequestException as req_err:
            logger.error(f"API Request error for {url}: {req_err}", exc_info=True)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response from {url}: {json_err}. Response text: {response.text[:200] if 'response' in locals() else 'N/A'}")
        return None

    def _search_youtube(self, query_text: str, max_results: int) -> list:
        """Search YouTube using the Data API v3."""
        if not self.youtube_api_key:
            logger.warning("YouTube API key not configured. Skipping Youtube.")
            return []
        
        search_url = "https://www.googleapis.com/youtube/v3/search"
        video_details_url = "https://www.googleapis.com/youtube/v3/videos"
        
        search_params = {
            "part": "snippet",
            "q": query_text,
            "type": "video",
            "maxResults": max_results,
            "key": self.youtube_api_key,
            "fields": "items(id(videoId),snippet(publishedAt,channelId,title,description,thumbnails(medium),channelTitle))" # Optimized fields
        }
        
        search_data = self._make_api_request(search_url, params=search_params)
        if not search_data or 'items' not in search_data:
            logger.error(f"Youtube API call failed or returned no items for query: {query_text}")
            return []

        video_ids = [item['id']['videoId'] for item in search_data['items'] if item.get('id', {}).get('videoId')]
        if not video_ids:
            return []

        # Get video details (like duration, exact view count) for these IDs
        video_params = {
            "part": "snippet,contentDetails,statistics", # Snippet for redundant info but ok, contentDetails for duration, statistics for views/likes
            "id": ",".join(video_ids),
            "key": self.youtube_api_key,
            "fields": "items(id,snippet(publishedAt,channelId,title,description,thumbnails(medium),channelTitle,tags,categoryId),contentDetails(duration),statistics(viewCount,likeCount,commentCount))"
        }
        details_data = self._make_api_request(video_details_url, params=video_params)
        
        results = []
        if details_data and 'items' in details_data:
            for item in details_data['items']:
                snippet = item.get('snippet', {})
                content_details = item.get('contentDetails', {})
                stats = item.get('statistics', {})
                
                duration_sec = parse_duration_to_seconds(content_details.get('duration'))
                
                # Try to parse publication date safely
                pub_date_iso = None
                try:
                    pub_date_iso = dateutil_parser.isoparse(snippet.get('publishedAt')).isoformat() if snippet.get('publishedAt') else None
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse YouTube publishedAt date '{snippet.get('publishedAt')}': {e}")

                video_item = {
                    "title": snippet.get('title'),
                    "original_url": f"https://www.youtube.com/watch?v={item['id']}",
                    "platform_name": "youtube",
                    "platform_video_id": item['id'],
                    "description": snippet.get('description'),
                    "thumbnail_url": snippet.get('thumbnails', {}).get('medium', {}).get('url'),
                    "publication_date_str": pub_date_iso,
                    "duration_str": str(duration_sec) if duration_sec is not None else None,
                    "uploader_name": snippet.get('channelTitle'),
                    "uploader_url": f"https://www.youtube.com/channel/{snippet.get('channelId')}",
                    "view_count_str": str(stats.get('viewCount', 0)),
                    "like_count_str": str(stats.get('likeCount', 0)),
                    "comment_count_str": str(stats.get('commentCount', 0)),
                    "tags_list": snippet.get('tags', []),
                    # "category_str": snippet.get('categoryId'), # TODO: Map categoryId to label if needed
                    "scraped_at_timestamp": datetime.utcnow().isoformat(),
                    "spider_name": "youtube_api"
                }
                results.append(video_item)
        return results

    def _search_vimeo(self, query_text: str, max_results: int) -> list:
        """Search Vimeo using their API."""
        if not self.vimeo_access_token:
            logger.warning("Vimeo access token not configured. Skipping Vimeo search.")
            return []

        search_url = "https://api.vimeo.com/videos"
        headers = {
            "Authorization": f"Bearer {self.vimeo_access_token}",
            "Accept": "application/vnd.vimeo.*+json;version=3.4"
        }
        params = {
            "query": query_text,
            "per_page": max_results,
            "sort": "relevant", # or "date", "plays", etc.
            "direction": "desc",
            "fields": "uri,name,description,link,duration,created_time,pictures.sizes,user.name,user.link,metadata.connections.comments.total,metadata.connections.likes.total,stats.plays,tags,categories.name,embed.html"
        }
        
        data = self._make_api_request(search_url, headers=headers, params=params)
        if not data or 'data' not in data:
            return []

        results = []
        for item in data['data']:
            thumb_url = None
            if item.get('pictures') and item['pictures']['sizes']:
                # Find a suitable thumbnail size, e.g., 640px wide or largest
                best_thumb = sorted([pic for pic in item['pictures']['sizes'] if pic.get('link')], key=lambda x: x.get('width', 0), reverse=True)
                if best_thumb:
                    thumb_url = best_thumb[0]['link']

            pub_date_iso = None
            try:
                pub_date_iso = dateutil_parser.isoparse(item.get('created_time')).isoformat() if item.get('created_time') else None
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse Vimeo created_time date '{item.get('created_time')}': {e}")

            video_item = {
                "title": item.get('name'),
                "original_url": item.get('link'),
                "platform_name": "vimeo",
                "platform_video_id": item.get('uri', '').split('/')[-1] if item.get('uri') else None, # Extract ID from URI
                "description": item.get('description'),
                "thumbnail_url": thumb_url,
                "publication_date_str": pub_date_iso,
                "duration_str": str(item.get('duration')) if item.get('duration') is not None else None, # Duration in seconds
                "uploader_name": item.get('user', {}).get('name'),
                "uploader_url": item.get('user', {}).get('link'),
                "view_count_str": str(item.get('stats', {}).get('plays', 0)),
                "like_count_str": str(item.get('metadata', {}).get('connections', {}).get('likes', {}).get('total', 0)),
                "comment_count_str": str(item.get('metadata', {}).get('connections', {}).get('comments', {}).get('total', 0)),
                "tags_list": [tag['name'] for tag in item.get('tags', []) if tag.get('name')],
                "category_str": ", ".join([cat['name'] for cat in item.get('categories', []) if cat.get('name')]),
                "embed_url": self._extract_vimeo_embed_url_from_html(item.get('embed', {}).get('html')),
                "scraped_at_timestamp": datetime.utcnow().isoformat(),
                "spider_name": "vimeo_api"
            }
            results.append(video_item)
        return results
        
    def _extract_vimeo_embed_url_from_html(self, embed_html:str) -> str | None:
        if not embed_html: return None
        match = re.search(r'src="([^"]+)"', embed_html)
        return match.group(1) if match else None


    def _search_dailymotion(self, query_text: str, max_results: int) -> list:
        """Search Dailymotion using their API."""
        # Dailymotion API might not require a key for public searches, or uses OAuth.
        # This example assumes a public search endpoint.
        search_url = settings.DAILYMOTION_API_URL + "/videos" # Or /rest/videos if using Partner API
        params = {
            "search": query_text,
            "limit": max_results,
            "sort": "relevance", # or "visited", "recent"
            "fields": "id,title,description,url,thumbnail_medium_url,created_time,duration,owner.screenname,owner.url,views_total,likes_total,comments_total,tags,channel.name,embed_url"
        }
        # Headers might be needed for specific API keys or OAuth tokens
        # headers = {"Authorization": f"Bearer {YOUR_DM_TOKEN}"}
        
        data = self._make_api_request(search_url, params=params) #, headers=headers if needed)
        if not data or 'list' not in data:
            return []

        results = []
        for item in data['list']:
            pub_date_iso = None
            if item.get('created_time'): # Unix timestamp
                try:
                    pub_date_iso = datetime.utcfromtimestamp(item['created_time']).isoformat()
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not parse Dailymotion created_time '{item.get('created_time')}': {e}")

            video_item = {
                "title": item.get('title'),
                "original_url": item.get('url'),
                "platform_name": "dailymotion",
                "platform_video_id": item.get('id'),
                "description": item.get('description'),
                "thumbnail_url": item.get('thumbnail_medium_url'), # Or other sizes
                "publication_date_str": pub_date_iso,
                "duration_str": str(item.get('duration')) if item.get('duration') is not None else None, # Duration in seconds
                "uploader_name": item.get('owner.screenname'),
                "uploader_url": item.get('owner.url'),
                "view_count_str": str(item.get('views_total', 0)),
                "like_count_str": str(item.get('likes_total', 0)),
                "comment_count_str": str(item.get('comments_total', 0)),
                "tags_list": item.get('tags', []),
                "category_str": item.get('channel.name'),
                "embed_url": item.get('embed_url'),
                "scraped_at_timestamp": datetime.utcnow().isoformat(),
                "spider_name": "dailymotion_api"
            }
            results.append(video_item)
        return results

    def _run_scrapy_spider(self, spider_name: str, spider_args: dict, output_file:str) -> bool:
        """
        Runs a Scrapy spider as a subprocess.
        spider_args: dictionary of arguments to pass to the spider.
        output_file: path to the temporary JSON file where results will be stored.
        Returns True if successful (exit code 0), False otherwise.
        """
        cmd = [
            self.scrapy_executable,
            "crawl",
            spider_name,
            "-o", output_file, # Output to a file in JSON lines format
            "-L", "INFO", # Log level
        ]
        # Add spider arguments
        for key, value in spider_args.items():
            if value is not None: # Ensure value is not None before converting to string
                cmd.extend(["-a", f"{key}={str(value)}"])
        
        logger.info(f"Running Scrapy command: {' '.join(cmd)} in CWD: {self.scrapers_project_dir}")
        
        try:
            # `cwd` is crucial: Scrapy commands need to be run from the project root
            # where scrapy.cfg is located (or where settings can be found).
            # If scrapy.cfg is inside `self.scrapers_project_dir`, use that.
            # The `ai_agents.scrapers.settings` should be discoverable by Scrapy.
            process = subprocess.Popen(cmd, cwd=self.scrapers_project_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate(timeout=300) # 5-minute timeout per spider
            exit_code = process.returncode

            if exit_code == 0:
                logger.info(f"Scrapy spider '{spider_name}' finished successfully. Output at {output_file}")
                return True
            else:
                logger.error(f"Scrapy spider '{spider_name}' failed with exit code {exit_code}.")
                if stdout: logger.error(f"Spider STDOUT: {stdout.decode(errors='ignore')}")
                if stderr: logger.error(f"Spider STDERR: {stderr.decode(errors='ignore')}")
                return False
        except subprocess.TimeoutExpired:
            logger.error(f"Scrapy spider '{spider_name}' timed out.")
            process.kill()
            return False
        except FileNotFoundError:
            logger.error(f"Scrapy executable '{self.scrapy_executable}' not found. Ensure Scrapy is installed and in PATH or provide full path.")
            return False
        except Exception as e:
            logger.error(f"Error running Scrapy spider '{spider_name}': {e}", exc_info=True)
            return False

    def _fetch_from_scrapeable_platforms(self, query_text: str, platforms_config: list) -> list:
        """
        Iterates through configured scrapeable platforms (like PeerTube instances) and runs spiders.
        `platforms_config` is a list of dicts from Django settings, e.g.:
        [{'name': 'PeerTube_Tilvids', 'spider_name': 'peertube', 'base_url': 'https://tilvids.com', 
          'search_path_template': '/api/v1/search/videos?search={query}', 'is_active': True, 
          'platform_identifier': 'peertube_tilvids'}]
        """
        all_scraped_results = []
        if not platforms_config:
            logger.info("No scrapeable platforms configured.")
            return all_scraped_results

        for platform_conf in platforms_config:
            if not platform_conf.get('is_active', False):
                logger.debug(f"Skipping inactive scrapeable platform: {platform_conf.get('name')}")
                continue

            spider_name = platform_conf.get('spider_name')
            base_url = platform_conf.get('base_url')
            search_template = platform_conf.get('search_path_template')
            platform_id = platform_conf.get('platform_identifier', f"scraped_{get_domain_from_url(base_url).split('.')[0]}") # Default identifier

            if not spider_name or not base_url:
                logger.warning(f"Skipping misconfigured scrapeable platform: {platform_conf.get('name')} (missing spider_name or base_url)")
                continue
            
            logger.info(f"Preparing to scrape platform: {platform_conf.get('name')} using spider: {spider_name} for query: '{query_text}'")

            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".jsonl") as tmp_output_file:
                output_filename = tmp_output_file.name
            
            spider_args = {
                "target_instance_base_url": base_url,
                "search_query": query_text, # Pass the user's query
                "search_path_template": search_template, # Template for constructing search URL
                "max_results": self.max_scraped_items,
                "platform_identifier": platform_id, # Pass specific identifier
                # Can also pass default_listing_url if defined in config
                "default_listing_url": platform_conf.get('default_listing_url')
            }
            
            success = self._run_scrapy_spider(spider_name, spider_args, output_filename)
            
            if success and os.path.exists(output_filename):
                try:
                    with open(output_filename, 'r') as f:
                        for line in f:
                            try:
                                scraped_item_dict = json.loads(line)
                                # Here, you could do some basic validation or transformation if needed
                                # before adding to all_scraped_results.
                                # The PapriVideoItem structure should align with what CAAgent expects.
                                all_scraped_results.append(scraped_item_dict)
                            except json.JSONDecodeError:
                                logger.warning(f"Could not decode JSON line from {output_filename}: {line.strip()}")
                except Exception as e:
                    logger.error(f"Error reading results from spider output file {output_filename}: {e}", exc_info=True)
                finally:
                    os.remove(output_filename) # Clean up temp file
            elif os.path.exists(output_filename): # Spider might have failed but still wrote a file
                 os.remove(output_filename)


            # Polite delay between scraping different platforms/instances
            time.sleep(self.scrape_inter_platform_delay) 

        logger.info(f"Total items scraped from all platforms: {len(all_scraped_results)}")
        return all_scraped_results


    def fetch_content_from_sources(self, processed_query_data: dict) -> list[dict]:
        """
        Main method to fetch content from all configured sources (APIs + Scrapers).
        `processed_query_data` comes from QAgent and contains `original_query_text`, `keywords`, etc.
        Returns a list of dictionaries, where each dictionary represents a potential video item
        (matching structure of PapriVideoItem or similar).
        """
        query_text = processed_query_data.get('original_query_text') # Use original text for broad API searches
        if not query_text and processed_query_data.get('keywords'): # Fallback to keywords if no original text
            query_text = " ".join(processed_query_data.get('keywords', []))

        if not query_text:
            logger.warning("SOIAgent: No usable query text found in processed_query_data. Cannot fetch from text-based sources.")
            # If it's a pure image query, this agent might not do much unless image search APIs are integrated here.
            # For now, assumes QAgent handles image query feature extraction, and RARAgent uses those features
            # against an existing indexed visual database. SOIAgent focuses on text-based fetching.
            return []

        all_results = []
        max_r = self.max_api_results

        # 1. Fetch from APIs
        logger.info(f"SOIAgent: Fetching from APIs for query: '{query_text}'")
        all_results.extend(self._search_youtube(query_text, max_r))
        all_results.extend(self._search_vimeo(query_text, max_r))
        all_results.extend(self._search_dailymotion(query_text, max_r))
        
        logger.info(f"SOIAgent: Fetched {len(all_results)} items from APIs.")

        # 2. Fetch from Scrapeable Platforms (e.g., PeerTube instances)
        scrapeable_platforms_config = getattr(settings, 'SCRAPEABLE_PLATFORMS_CONFIG', [])
        if scrapeable_platforms_config:
            logger.info(f"SOIAgent: Fetching from scrapeable platforms for query: '{query_text}'")
            scraped_items = self._fetch_from_scrapeable_platforms(query_text, scrapeable_platforms_config)
            all_results.extend(scraped_items)
            logger.info(f"SOIAgent: Added {len(scraped_items)} items from scraping. Total items now: {len(all_results)}")
        else:
            logger.info("SOIAgent: No scrapeable platforms configured in Django settings.")

        # TODO: Add deduplication logic here? Or leave it for RARAgent?
        # Basic deduplication by original_url might be useful here.
        # For now, return all, RARAgent will handle robust deduplication.
        
        # Post-process all results to ensure basic structure and parse some fields
        final_processed_results = []
        for raw_item in all_results:
            # Ensure essential fields are present and try to parse common ones
            # This mirrors some of what the PapriVideoItem fields are for
            parsed_item = {
                "title": raw_item.get("title"),
                "original_url": raw_item.get("original_url"),
                "platform_name": raw_item.get("platform_name"),
                "platform_video_id": raw_item.get("platform_video_id"),
                "description": raw_item.get("description"),
                "thumbnail_url": raw_item.get("thumbnail_url"),
                "publication_date_iso": raw_item.get("publication_date_str"), # Already ISO string from API handlers
                "duration_seconds": parse_duration_to_seconds(raw_item.get("duration_str")) if raw_item.get("duration_str") else None,
                "uploader_name": raw_item.get("uploader_name"),
                "uploader_url": raw_item.get("uploader_url"),
                "view_count": int(raw_item.get("view_count_str", 0)) if raw_item.get("view_count_str", "0").isdigit() else 0,
                "like_count": int(raw_item.get("like_count_str", 0)) if raw_item.get("like_count_str", "0").isdigit() else 0,
                "comment_count": int(raw_item.get("comment_count_str", 0)) if raw_item.get("comment_count_str", "0").isdigit() else 0,
                "tags": raw_item.get("tags_list", []),
                "category": raw_item.get("category_str"),
                "embed_url": raw_item.get("embed_url"),
                "transcript_text": raw_item.get("transcript_text"),
                "transcript_vtt_url": raw_item.get("transcript_vtt_url"),
                "scraped_at_iso": raw_item.get("scraped_at_timestamp", datetime.utcnow().isoformat()), # Ensure it exists
                "fetch_source_type": raw_item.get("spider_name", "unknown_api_or_scraper") # youtube_api, peertube_api, peertube_scraper etc.
            }
            if parsed_item["title"] and parsed_item["original_url"]: # Minimal validation
                final_processed_results.append(parsed_item)
            else:
                logger.warning(f"SOIAgent: Skipping item due to missing title or URL after processing: {str(raw_item)[:200]}")

        logger.info(f"SOIAgent finished fetching. Total processed items: {len(final_processed_results)}")
        return final_processed_results

    def fetch_specific_video_details(self, video_url: str) -> dict | None:
        """
        Fetches detailed metadata for a single video URL.
        This would involve determining the platform and using the appropriate API/scraper.
        This is a more complex task if the platform isn't easily identifiable or requires specific spider runs.
        For now, this is a placeholder. A robust implementation would:
        1. Identify platform from URL.
        2. Call specific API (e.g., _search_youtube with video ID) or run a targeted scraper.
        """
        logger.info(f"SOIAgent attempting to fetch specific video details for URL: {video_url} (Placeholder)")
        # Example:
        # platform = self._identify_platform_from_url(video_url)
        # if platform == "youtube":
        #     video_id = self._extract_youtube_id(video_url)
        #     return self._get_youtube_video_details_by_id(video_id) # Implement this
        # elif platform == "vimeo":
        #     ...
        # else:
        #     # May need to run a scraper targeted at this single URL
        #     pass
        return {"warning": "Fetching specific video details is not fully implemented yet.", "original_url": video_url}
