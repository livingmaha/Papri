# backend/ai_agents/scrapers/items.py
import scrapy

class PapriVideoItem(scrapy.Item):
    # Core fields that match VideoSource or can be mapped to it
    title = scrapy.Field()
    original_url = scrapy.Field() # Unique URL of the video on the platform
    platform_name = scrapy.Field() # e.g., 'peertube_tilvids', 'rumble_channel_xyz'
    platform_video_id = scrapy.Field() # Video ID specific to the platform
    
    description = scrapy.Field()
    thumbnail_url = scrapy.Field()
    publication_date_str = scrapy.Field() # Raw string, to be parsed later
    duration_str = scrapy.Field() # Raw string, e.g., "10:30", to be parsed to seconds
    
    uploader_name = scrapy.Field()
    uploader_url = scrapy.Field()
    
    view_count_str = scrapy.Field() # Raw string
    like_count_str = scrapy.Field() # Raw string
    comment_count_str = scrapy.Field() # Raw string
    
    tags_list = scrapy.Field() # List of tag strings
    category_str = scrapy.Field() # Category as a string
    
    # Technical metadata from scraping
    scraped_at_timestamp = scrapy.Field()
    spider_name = scrapy.Field() # Name of the spider that scraped this item
    
    # Raw transcript or link to VTT if available directly from scrape
    transcript_text = scrapy.Field()
    transcript_vtt_url = scrapy.Field()

    # Other platform-specific fields can be added as needed
    # For example, embed_url if easily available
    embed_url = scrapy.Field()
