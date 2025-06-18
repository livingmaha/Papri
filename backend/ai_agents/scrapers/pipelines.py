# backend/ai_agents/scrapers/pipelines.py

from itemadapter import ItemAdapter
# from api.models import YourTargetModel # Import your Django model

class PapriScraperPipeline:
    """
    A Scrapy pipeline to process and save scraped items into the Django database.
    """
    def process_item(self, item, spider):
        """
        This method is called for every item pipeline component.

        It should either return an item, raise a DropItem exception, or return a
        deferred for asynchronous processing.
        """
        adapter = ItemAdapter(item)

        # --- Data Cleaning & Validation ---
        # Example: Strip whitespace from a 'title' field if it exists
        if 'title' in adapter:
            adapter['title'] = adapter['title'].strip()

        # Example: Check for required fields and drop the item if one is missing
        if not adapter.get('unique_id'):
            # from scrapy.exceptions import DropItem
            # raise DropItem(f"Missing unique ID in {item}")
            pass

        # --- Saving to Database ---
        # Here you would convert the Scrapy item into a Django model instance and save it.
        # Make sure your Scrapy project is configured to work with Django.
        # try:
        #     item.save() # If using scrapy-djangoitem
        # except Exception as e:
        #     spider.logger.error(f"Failed to save item to database: {e}")

        # For now, we just log the item
        spider.logger.info(f"Processing item: {adapter.asdict()}")

        return item
