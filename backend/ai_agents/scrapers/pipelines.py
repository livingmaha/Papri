# backend/ai_agents/scrapers/pipelines.py
import logging
from itemadapter import ItemAdapter
from django.db import transaction
from django.utils.dateparse import parse_datetime
from api.models import Video, VideoSource, VideoTag, VideoCategory
from .items import PapriVideoItem

logger = logging.getLogger(__name__)

class PapriScraperPipeline:
    """
    A Scrapy pipeline to process and save scraped PapriVideoItem into the Django database.
    """

    def process_item(self, item, spider):
        """
        This method is called for every item pipeline component.
        It converts the Scrapy item into Django model instances and saves them.
        """
        adapter = ItemAdapter(item)

        if not isinstance(item, PapriVideoItem):
            return item

        try:
            with transaction.atomic():
                # --- Get or Create Category ---
                category_name = adapter.get('category')
                category = None
                if category_name:
                    category, _ = VideoCategory.objects.get_or_create(name=category_name.strip())

                # --- Get or Create VideoSource and Video ---
                video_source, created = VideoSource.objects.update_or_create(
                    platform_name=adapter.get('platform_name'),
                    platform_video_id=adapter.get('platform_video_id'),
                    defaults={
                        'original_url': adapter.get('original_url'),
                        'embed_url': adapter.get('embed_url'),
                        'primary_thumbnail_url': adapter.get('primary_thumbnail_url'),
                        'channel_name': adapter.get('channel_name'),
                        'channel_url': adapter.get('channel_url'),
                        'channel_platform_id': adapter.get('channel_platform_id'),
                        'raw_api_data': adapter.get('raw_api_data'),
                    }
                )

                # --- Get or Create Video ---
                if created:
                    video = Video.objects.create(
                        title=adapter.get('title'),
                        description=adapter.get('description'),
                        duration_seconds=adapter.get('duration_seconds'),
                        publication_date=parse_datetime(adapter.get('publication_date')),
                        view_count=adapter.get('view_count'),
                        like_count=adapter.get('like_count'),
                        dislike_count=adapter.get('dislike_count'),
                        comment_count=adapter.get('comment_count'),
                        category=category
                    )
                    video_source.video = video
                    video_source.save()
                else:
                    video = video_source.video
                    # Update video fields if they are newer
                    video.title = adapter.get('title')
                    video.description = adapter.get('description')
                    video.duration_seconds = adapter.get('duration_seconds')
                    video.publication_date = parse_datetime(adapter.get('publication_date'))
                    video.view_count = adapter.get('view_count')
                    video.like_count = adapter.get('like_count')
                    video.dislike_count = adapter.get('dislike_count')
                    video.comment_count = adapter.get('comment_count')
                    video.category = category
                    video.save()

                # --- Handle Tags (Many-to-Many) ---
                tags_list = adapter.get('tags', [])
                if tags_list:
                    video.tags.clear()
                    for tag_name in tags_list:
                        tag, _ = VideoTag.objects.get_or_create(name=tag_name.strip())
                        video.tags.add(tag)
                
                logger.info(f"Successfully processed and saved video: {video.title}")

        except Exception as e:
            logger.error(f"Error processing item in pipeline: {e}", exc_info=True)
            # Optionally, you can raise a DropItem exception here
            # from scrapy.exceptions import DropItem
            # raise DropItem(f"Error saving to DB: {e}")

        return item
