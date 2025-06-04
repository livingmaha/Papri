# backend/ai_agents/main_orchestrator.py
import logging
import os
from datetime import datetime, timezone as dt_timezone
from typing import Dict, Any, List, Optional

from django.conf import settings
from django.utils import timezone as django_timezone # For Django model updates
from django.db import transaction # For atomic DB operations

# Import agent classes
from .query_understanding_agent import QueryUnderstandingAgent
from .source_orchestration_agent import SourceOrchestrationAgent
from .content_analysis_agent import ContentAnalysisAgent
from .result_aggregation_agent import ResultAggregationAgent
from .memory_module import MemoryModule # Using the stubbed MemoryModule

# Import Django models (use carefully to avoid circular dependencies at import time)
# It's generally safer to fetch/update models via primary keys passed around,
# or import within methods if issues arise.
from api.models import SearchTask, Video, VideoSource, UserProfile

from .utils import generate_deduplication_hash, normalize_text_unicode # Utility functions

logger = logging.getLogger(__name__)

class PapriAIAgentOrchestrator:
    def __init__(self, papri_search_task_id: str):
        """
        Initializes the orchestrator for a specific search task.
        `papri_search_task_id` is the UUID of the SearchTask Django model instance.
        """
        self.papri_search_task_id = papri_search_task_id
        
        # Instantiate all subordinate agents
        self.q_agent = QueryUnderstandingAgent()
        self.so_agent = SourceOrchestrationAgent()
        self.ca_agent = ContentAnalysisAgent()
        self.ra_agent = ResultAggregationAgent()
        
        # Memory module initialized per search task (can be enhanced for user/session persistence)
        self.memory = MemoryModule(session_id=str(papri_search_task_id)) # Using search task ID as a session for now

        logger.info(f"PapriAIAgentOrchestrator initialized for SearchTask ID: {self.papri_search_task_id}")

    def _update_search_task_status(self, status: str, error_message: Optional[str] = None, progress_percent: Optional[int] = None):
        """Helper to update the SearchTask model instance in the database."""
        try:
            # Re-fetch task to ensure we have the latest version if this method is called multiple times
            task = SearchTask.objects.get(id=self.papri_search_task_id)
            task.status = status
            if error_message:
                task.error_message = (task.error_message or "") + error_message + " "
            # if progress_percent is not None:
            #     task.progress = progress_percent # Assuming SearchTask has a 'progress' field
            task.updated_at = django_timezone.now()
            task.save(update_fields=['status', 'error_message', 'updated_at']) # Add 'progress' if using
            logger.debug(f"SearchTask {self.papri_search_task_id} status updated to: {status}")
        except SearchTask.DoesNotExist:
            logger.error(f"SearchTask {self.papri_search_task_id} not found for status update.")
        except Exception as e:
            logger.error(f"Error updating SearchTask {self.papri_search_task_id} status: {e}", exc_info=True)

    @transaction.atomic # Ensure DB operations within this step are atomic
    def _persist_raw_video_item(self, raw_item_data: Dict[str, Any], search_task_user_id: Optional[int]) -> Optional[VideoSource]:
        """
        Persists a single raw video item (from SOIAgent) to Video and VideoSource models.
        Handles deduplication based on title and duration for the canonical Video.
        Returns the VideoSource Django model instance if successful.
        """
        if not raw_item_data.get('title') or not raw_item_data.get('original_url'):
            logger.warning(f"Skipping persistence for raw item due to missing title or URL: {str(raw_item_data)[:200]}")
            return None

        title = normalize_text_unicode(raw_item_data['title'])
        duration_seconds = raw_item_data.get('duration_seconds') # Already parsed by SOIAgent
        platform_video_id = raw_item_data.get('platform_video_id')
        platform_name = raw_item_data.get('platform_name')

        # 1. Get or Create Canonical Video (Deduplication)
        # Simple dedupe hash; more advanced methods could be used.
        dedupe_hash = generate_deduplication_hash(title, duration_seconds, platform_video_id if platform_name not in ['user_upload', 'other_scrape'] else None)
        
        video_defaults = {
            'title': title[:499], # Ensure it fits model CharField limit
            'description': raw_item_data.get('description'),
            'duration_seconds': duration_seconds,
            'tags': raw_item_data.get('tags', []),
            'category': raw_item_data.get('category'),
        }
        if raw_item_data.get('publication_date_iso'):
            try:
                video_defaults['publication_date'] = datetime.fromisoformat(raw_item_data['publication_date_iso'].replace('Z', '+00:00'))
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid publication_date_iso format '{raw_item_data['publication_date_iso']}': {e}. Skipping date for Video.")


        canonical_video, video_created = Video.objects.update_or_create(
            deduplication_hash=dedupe_hash, # Primary key for deduplication
            defaults=video_defaults
        )
        if video_created:
            logger.info(f"Created new Canonical Video (ID: {canonical_video.id}) for title: '{title[:50]}...' Hash: {dedupe_hash}")
        else: # Video existed, update its fields if new data is better (e.g., longer description)
            # For simplicity, update_or_create with defaults handles this if defaults are more complete.
            # Or add explicit update logic here if needed.
            logger.debug(f"Found existing Canonical Video (ID: {canonical_video.id}) for Hash: {dedupe_hash}. Updating if necessary.")
            # Ensure all fields in video_defaults are updated if the record exists
            for key, value in video_defaults.items():
                 if getattr(canonical_video, key) != value and value is not None : # Update if different and new value not None
                    setattr(canonical_video, key, value)
            canonical_video.save()


        # 2. Get or Create VideoSource
        source_defaults = {
            'video': canonical_video,
            'embed_url': raw_item_data.get('embed_url'),
            'thumbnail_url': raw_item_data.get('thumbnail_url'),
            'uploader_name': raw_item_data.get('uploader_name'),
            'uploader_url': raw_item_data.get('uploader_url'),
            'view_count': raw_item_data.get('view_count', 0),
            'like_count': raw_item_data.get('like_count', 0),
            'comment_count': raw_item_data.get('comment_count', 0),
            'processing_status': 'metadata_fetched', # Initial status after SOIAgent
            'last_scraped_at': django_timezone.now(), # Should be set by SOIAgent ideally, or here
        }
        if raw_item_data.get('scraped_at_iso'): # If SOIAgent provides it
            try:
                source_defaults['last_scraped_at'] = datetime.fromisoformat(raw_item_data['scraped_at_iso'].replace('Z', '+00:00'))
            except (ValueError, TypeError): pass


        video_source_obj, source_created = VideoSource.objects.update_or_create(
            original_url=raw_item_data['original_url'], # Unique constraint on original_url
            defaults={
                'platform_name': platform_name,
                'platform_video_id': platform_video_id,
                **source_defaults # Spread the rest of defaults
            }
        )
        if source_created:
            logger.info(f"Created new VideoSource (ID: {video_source_obj.id}) for URL: {video_source_obj.original_url}")
        else:
            logger.debug(f"Found existing VideoSource (ID: {video_source_obj.id}) for URL: {video_source_obj.original_url}. Updated.")
            # If updating, ensure status doesn't regress if it was already further along.
            # This logic can be complex. For now, update_or_create overwrites if defaults differ.
            # Consider only updating if new data is "better" or status is earlier.
            if video_source_obj.processing_status not in ['analysis_complete', 'transcript_processing', 'visual_processing']: # Don't regress from active/completed states
                video_source_obj.processing_status = 'metadata_fetched' # Reset for re-analysis if needed
            
            # Update other fields if changed
            for key, value in source_defaults.items():
                 if getattr(video_source_obj, key) != value and value is not None:
                    setattr(video_source_obj, key, value)
            video_source_obj.save()

        return video_source_obj


    def execute_search(self, search_parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main orchestration logic for a search query.
        `search_parameters` includes query_text, query_image_path, filters, user_id, session_id.
        Returns a dictionary suitable for the Celery task to update SearchTask model.
        """
        logger.info(f"Orchestrator: Executing search for STID {self.papri_search_task_id} with params: {str(search_parameters)[:300]}...")
        self._update_search_task_status('processing', progress_percent=5)
        
        # Retrieve user preferences if user is authenticated
        user_prefs = None
        if search_parameters.get('user_id'):
            user_prefs = self.memory.get_user_preference("search_settings") # Example
            # Or directly:
            # try:
            #     user_profile = UserProfile.objects.get(user_id=search_parameters['user_id'])
            #     user_prefs = user_profile.preferences_json # Assuming it's a JSON field
            # except UserProfile.DoesNotExist: pass

        # --- Stage 1: Query Understanding ---
        logger.debug(f"STID {self.papri_search_task_id}: Initiating Query Understanding.")
        self._update_search_task_status('processing', progress_percent=10)
        
        processed_query_data = None
        query_text = search_parameters.get('query_text')
        query_image_path = search_parameters.get('query_image_path')
        query_video_url = search_parameters.get('query_video_url')

        if query_video_url: # Specific video URL analysis query
            processed_query_data = self.q_agent.process_video_url_query(query_video_url, query_text)
        elif query_text and query_image_path:
            processed_query_data = self.q_agent.process_hybrid_query(query_text, query_image_path)
        elif query_text:
            processed_query_data = self.q_agent.process_text_query(query_text)
        elif query_image_path:
            processed_query_data = self.q_agent.process_image_query(query_image_path)
        else:
            logger.error(f"STID {self.papri_search_task_id}: No valid query input provided to QAgent.")
            self._update_search_task_status('failed', error_message="No query input (text, image, or URL).")
            return {"error": "No query input provided.", "search_status_overall": "failed"}

        if not processed_query_data or "error" in processed_query_data:
            er_msg = processed_query_data.get("error", "Query understanding failed.") if processed_query_data else "Query understanding failed."
            logger.error(f"STID {self.papri_search_task_id}: QAgent failed: {er_msg}")
            self._update_search_task_status('failed', error_message=f"QAgent: {er_msg}")
            return {"error": er_msg, "search_status_overall": "failed"}
        
        self.memory.update_short_term_context("processed_query", processed_query_data)
        logger.info(f"STID {self.papri_search_task_id}: QAgent processing complete. Intent: {processed_query_data.get('intent')}")
        self._update_search_task_status('processing', progress_percent=20)

        # --- Stage 2: Source Orchestration & Interfacing ---
        # SOIAgent fetches raw metadata from various platforms.
        logger.debug(f"STID {self.papri_search_task_id}: Initiating Source Orchestration.")
        self._update_search_task_status('processing', progress_percent=30)

        # For "analyze_specific_video" intent, SOIAgent might fetch details for that single URL.
        # For other search intents, it queries multiple sources.
        raw_video_items_from_soi: List[Dict[str, Any]] = []
        if processed_query_data.get('intent') == "analyze_specific_video":
            single_video_details = self.so_agent.fetch_specific_video_details(processed_query_data['original_video_url'])
            if single_video_details and not single_video_details.get("warning"): # Assuming success if no warning for placeholder
                raw_video_items_from_soi.append(single_video_details)
        elif processed_query_data.get('intent') != "visual_similarity_search_only_internal": # Avoid if pure visual search on existing index
            raw_video_items_from_soi = self.so_agent.fetch_content_from_sources(processed_query_data)
        
        logger.info(f"STID {self.papri_search_task_id}: SOIAgent fetched {len(raw_video_items_from_soi)} raw video items.")
        self._update_search_task_status('processing', progress_percent=50)

        # --- Stage 3: Persist Basic Video Info & Content Analysis ---
        # Persist fetched items to DB (Video, VideoSource) and then trigger content analysis.
        # This loop can be long; consider batching DB writes or offloading parts to sub-tasks if performance is an issue.
        
        persisted_video_sources_for_rar: List[VideoSource] = [] # For RARAgent if it needs Django objects
        analyzed_count = 0
        
        if raw_video_items_from_soi:
            logger.debug(f"STID {self.papri_search_task_id}: Persisting and analyzing {len(raw_video_items_from_soi)} items.")
            for i, raw_item in enumerate(raw_video_items_from_soi):
                # Persist first
                video_source_obj = self._persist_raw_video_item(raw_item, search_parameters.get('user_id'))
                if not video_source_obj:
                    logger.warning(f"STID {self.papri_search_task_id}: Failed to persist raw_item: {str(raw_item)[:100]}")
                    continue
                
                persisted_video_sources_for_rar.append(video_source_obj) # Add to list for RARAgent context

                # Check if analysis is needed (e.g., based on last_analyzed_at or processing_status)
                # For simplicity, let's assume we re-analyze if status is not 'analysis_complete'
                # or if it's a new source (video_source_obj.created_at approx now).
                # A more robust check would compare last_scraped_at with last_analyzed_at.
                needs_analysis = True # Default to True for new/updated items
                if video_source_obj.last_analyzed_at and video_source_obj.processing_status == 'analysis_complete':
                    # Example: Re-analyze if content was scraped more recently than last analysis
                    # Or if it's older than X days (e.g. 30 days for content refresh)
                    if video_source_obj.last_scraped_at and video_source_obj.last_scraped_at > video_source_obj.last_analyzed_at:
                        needs_analysis = True
                    elif (django_timezone.now() - video_source_obj.last_analyzed_at) > timedelta(days=30): # Configurable
                        needs_analysis = True
                    else:
                        needs_analysis = False 
                        logger.debug(f"STID {self.papri_search_task_id}: Skipping analysis for already analyzed VSID {video_source_obj.id}")
                
                if needs_analysis:
                    logger.debug(f"STID {self.papri_search_task_id}: Triggering CAAgent for VSID {video_source_obj.id}")
                    analysis_report = self.ca_agent.analyze_video_content(video_source_obj, raw_item)
                    # CAAgent updates VideoSource status internally. Log its report.
                    logger.debug(f"STID {self.papri_search_task_id}: CAAgent report for VSID {video_source_obj.id}: {analysis_report}")
                    analyzed_count += 1
                
                # Update overall progress (approximate)
                current_progress = 50 + int((i + 1) / len(raw_video_items_from_soi) * 30) # Analysis is 30% of remaining
                self._update_search_task_status('processing', progress_percent=current_progress)

            logger.info(f"STID {self.papri_search_task_id}: Persisted {len(persisted_video_sources_for_rar)} sources. Triggered analysis for {analyzed_count} of them.")
        else:
            logger.info(f"STID {self.papri_search_task_id}: No new items from SOIAgent to persist/analyze. Proceeding to aggregation with existing index.")
        
        self._update_search_task_status('processing', progress_percent=85)


        # --- Stage 4: Result Aggregation & Ranking ---
        logger.debug(f"STID {self.papri_search_task_id}: Initiating Result Aggregation & Ranking.")
        # RARAgent uses processed_query_data and user_filters.
        # It will query Qdrant and DB based on this, and use `persisted_video_sources_for_rar`
        # only if it needs to consider *just-fetched* items specifically (e.g. for boosting them).
        # The current RARAgent design focuses on Qdrant/DB state.
        
        final_ranked_results_for_task = self.ra_agent.aggregate_and_rank_results(
            processed_query_data=processed_query_data,
            # current_session_video_sources=persisted_video_sources_for_rar, # Pass if RARAgent uses it
            user_filters=search_parameters.get('applied_filters', {}),
            user_preferences=user_prefs
        )
        
        if not final_ranked_results_for_task and not raw_video_items_from_soi: # No new items and no results from index
            logger.info(f"STID {self.papri_search_task_id}: RARAgent returned no results, and no new items were fetched.")
            # No error if query was valid but just no matches found.
            self._update_search_task_status('completed', progress_percent=100) # Mark as complete
            return {
                "message": "Search complete. No results found matching your query.",
                "search_status_overall": "completed",
                "persisted_video_ids_ranked": [],
                "results_data_detailed": []
            }
        elif not final_ranked_results_for_task and raw_video_items_from_soi :
             logger.info(f"STID {self.papri_search_task_id}: RARAgent returned no results, but new items were fetched and analyzed. This might indicate an issue or no relevant matches.")
             # This might be ok if none of the new items matched the query well after analysis.


        logger.info(f"STID {self.papri_search_task_id}: RARAgent processing complete. Returned {len(final_ranked_results_for_task)} items.")
        self._update_search_task_status('completed', progress_percent=100) # Final state

        # The structure of `final_ranked_results_for_task` should be a list of dicts,
        # where each dict contains 'video_id' (canonical), 'combined_score', 'match_types',
        # and 'best_source' (which itself is a dict with source-specific details).
        # This directly maps to SearchTask.detailed_results_info_json.
        
        # Extract just the canonical video IDs in ranked order for SearchTask.result_video_ids_json
        ranked_canonical_video_ids = [item['video_id'] for item in final_ranked_results_for_task if 'video_id' in item]

        return {
            "message": "Search orchestrated successfully.",
            "search_status_overall": "completed", # Or "partial_results" if applicable
            "items_fetched_from_sources": len(raw_video_items_from_soi),
            "items_newly_analyzed": analyzed_count,
            "ranked_video_count": len(ranked_canonical_video_ids),
            "persisted_video_ids_ranked": ranked_canonical_video_ids, # For SearchTask.result_video_ids_json
            "results_data_detailed": final_ranked_results_for_task    # For SearchTask.detailed_results_info_json
        }

# Example of how Celery task might call this (already in api/tasks.py):
# from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator
# @shared_task
# def process_search_query(search_task_id):
#     orchestrator = PapriAIAgentOrchestrator(search_task_id)
#     results = orchestrator.execute_search(search_parameters_from_task_model)
#     # Update SearchTask model with results
