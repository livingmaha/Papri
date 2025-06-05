# backend/ai_agents/main_orchestrator.py
import logging
import os
from datetime import datetime, timedelta # Ensure timedelta is imported
from typing import Dict, Any, List, Optional

from django.conf import settings
from django.utils import timezone as django_timezone # For Django model updates
from django.db import transaction # For atomic DB operations, critical for data integrity

# Import agent classes
from .query_understanding_agent import QueryUnderstandingAgent
from .source_orchestration_agent import SourceOrchestrationAgent
from .content_analysis_agent import ContentAnalysisAgent
from .result_aggregation_agent import ResultAggregationAgent
from .memory_module import MemoryModule # Using the stubbed MemoryModule

# Import Django models
from api.models import SearchTask, Video, VideoSource, UserProfile # Assuming UserProfile for user_prefs

from .utils import generate_deduplication_hash, normalize_text_unicode # Utility functions

logger = logging.getLogger(__name__) # Standard Python logger for this module

class PapriAIAgentOrchestrator:
    def __init__(self, papri_search_task_id: str):
        """
        Initializes the orchestrator for a specific search task.
        `papri_search_task_id` is the UUID of the SearchTask Django model instance.
        """
        self.papri_search_task_id = papri_search_task_id # Store the SearchTask ID
        
        # Instantiate all subordinate agents. These should be lightweight to instantiate.
        # Heavy model loading should ideally be lazy within each agent or done once globally if possible.
        self.q_agent = QueryUnderstandingAgent()
        self.so_agent = SourceOrchestrationAgent()
        self.ca_agent = ContentAnalysisAgent()
        self.ra_agent = ResultAggregationAgent()
        
        # Initialize memory module, potentially scoped to this search task or user/session
        self.memory = MemoryModule(session_id=str(papri_search_task_id)) 

        logger.info(f"PapriAIAgentOrchestrator initialized for SearchTask ID: {self.papri_search_task_id}")

    def _update_search_task_status(self, status: str, error_message: Optional[str] = None, progress_percent: Optional[int] = None, clear_error: bool = False):
        """
        Helper to update the SearchTask model instance in the database.
        `clear_error`: If True, it will clear any existing error message.
        """
        try:
            # It's good practice to re-fetch the task object if updates are frequent or from different points
            task = SearchTask.objects.get(id=self.papri_search_task_id)
            task.status = status
            
            if clear_error:
                task.error_message = None
            elif error_message:
                # Append new error message to existing ones, if any, to preserve history of issues.
                existing_error = task.error_message or ""
                if existing_error and not existing_error.endswith(". "):
                    existing_error += ". "
                task.error_message = (existing_error + error_message)[:1000] # Keep within reasonable length

            # Assuming SearchTask model has a 'progress' field (IntegerField or FloatField)
            # if progress_percent is not None:
            #     task.progress = progress_percent 
            
            task.updated_at = django_timezone.now()
            
            update_fields = ['status', 'updated_at']
            if error_message or clear_error:
                update_fields.append('error_message')
            # if progress_percent is not None:
            #     update_fields.append('progress')
                
            task.save(update_fields=update_fields)
            logger.debug(f"SearchTask {self.papri_search_task_id} status updated to: {status}. Progress: {progress_percent}%. Error: {task.error_message}")
        except SearchTask.DoesNotExist:
            logger.error(f"SearchTask {self.papri_search_task_id} not found for status update. Critical error.")
            # This is a critical issue if the task ID is valid but object vanishes.
        except Exception as e:
            logger.error(f"Error updating SearchTask {self.papri_search_task_id} status: {e}", exc_info=True)

    @transaction.atomic # Ensures all database operations within this method are committed together or rolled back.
    def _persist_raw_video_item(self, raw_item_data: Dict[str, Any], search_task_user_id: Optional[int]) -> Optional[VideoSource]:
        """
        Persists a single raw video item from SOIAgent to Video and VideoSource models.
        Handles deduplication for the canonical Video.
        Returns the VideoSource Django model instance if successful, otherwise None.
        """
        # Validate essential data from raw_item_data
        title = raw_item_data.get('title')
        original_url = raw_item_data.get('original_url')
        platform_name = raw_item_data.get('platform_name')
        platform_video_id = raw_item_data.get('platform_video_id')

        if not title or not original_url or not platform_name or not platform_video_id:
            logger.warning(f"Skipping persistence for raw item due to missing critical fields (title, original_url, platform_name, or platform_video_id): {str(raw_item_data)[:250]}")
            return None

        normalized_title = normalize_text_unicode(title)[:499] # Normalize and truncate
        duration_seconds = raw_item_data.get('duration_seconds') # Assumed parsed by SOIAgent

        # 1. Get or Create Canonical Video (Deduplication)
        # Deduplication hash might be more robust using multiple strong identifiers.
        # For example, platform_name + platform_video_id is a strong unique key for a specific video instance.
        # If aiming for cross-platform deduplication, title + duration is a heuristic.
        # Let's refine the dedupe_hash. If it's a known platform, its ID is king.
        if platform_name not in ['user_upload', 'other_scrape', 'unknown_api_or_scraper']:
             # For known platforms, assume platform_video_id is the primary dedupe factor combined with platform
             # This means a video re-uploaded to same platform with same ID is the same.
             # To find a *truly* canonical video across platforms, more advanced content hashing (visual/audio) is needed.
             # For now, our "canonical" Video might be less about "same exact content" and more "same primary title/duration".
             dedupe_hash_content_part = generate_deduplication_hash(normalized_title, duration_seconds)
             # A more specific hash if we want less aggressive canonicalization across platforms:
             # dedupe_hash = f"{platform_name}_{platform_video_id}" # This makes Video almost same as VideoSource.
             # Let's stick to title/duration for canonical Video, understanding its limitations.
             dedupe_hash = dedupe_hash_content_part
        else: # For uploads or generic scrapes, rely on title/duration
             dedupe_hash = generate_deduplication_hash(normalized_title, duration_seconds)
        
        video_defaults = {
            'title': normalized_title,
            'description': raw_item_data.get('description'),
            'duration_seconds': duration_seconds,
            'tags': raw_item_data.get('tags', []),
            'category': raw_item_data.get('category'),
        }
        if raw_item_data.get('publication_date_iso'):
            try:
                # Ensure ISO string is timezone-aware or correctly converted
                pub_date_str = raw_item_data['publication_date_iso']
                if 'Z' in pub_date_str.upper():
                    video_defaults['publication_date'] = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                else: # Assume naive UTC if no timezone info, or parse with dateutil for more flexibility
                    video_defaults['publication_date'] = datetime.fromisoformat(pub_date_str).replace(tzinfo=dt_timezone.utc)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid publication_date_iso format '{raw_item_data.get('publication_date_iso')}': {e}. Skipping date for Video.")

        try:
            canonical_video, video_created = Video.objects.update_or_create(
                deduplication_hash=dedupe_hash,
                defaults=video_defaults
            )
            if video_created:
                logger.info(f"CREATED new Canonical Video (ID: {canonical_video.id}) for title: '{normalized_title[:50]}...' Hash: {dedupe_hash}")
            else: # Video existed, update its fields if new data is more complete or recent.
                changed = False
                for key, value in video_defaults.items():
                    if value is not None and getattr(canonical_video, key) != value:
                        # Specific logic for updates, e.g., only update description if new one is longer
                        if key == 'description' and value and (not canonical_video.description or len(value) > len(canonical_video.description)):
                            setattr(canonical_video, key, value)
                            changed = True
                        elif key != 'description': # For other fields, update if different
                            setattr(canonical_video, key, value)
                            changed = True
                if changed:
                    canonical_video.updated_at = django_timezone.now() # Manually set if not auto_now
                    canonical_video.save()
                    logger.info(f"UPDATED existing Canonical Video (ID: {canonical_video.id}) for Hash: {dedupe_hash}.")
                else:
                     logger.debug(f"Found existing Canonical Video (ID: {canonical_video.id}), no updates needed.")
        except Exception as e:
            logger.error(f"Database error creating/updating Canonical Video with hash {dedupe_hash}: {e}", exc_info=True)
            return None


        # 2. Get or Create VideoSource
        source_defaults = {
            'video': canonical_video, # Link to the canonical video
            'platform_name': platform_name,
            'platform_video_id': platform_video_id,
            'embed_url': raw_item_data.get('embed_url'),
            'thumbnail_url': raw_item_data.get('thumbnail_url'),
            'uploader_name': raw_item_data.get('uploader_name'),
            'uploader_url': raw_item_data.get('uploader_url'),
            'view_count': raw_item_data.get('view_count', 0),
            'like_count': raw_item_data.get('like_count', 0),
            'comment_count': raw_item_data.get('comment_count', 0),
            # Initial status before CAAgent runs. If CAAgent runs, it will update this.
            'processing_status': 'metadata_fetched', 
            'meta_visual_processing_status': 'pending', # Reset visual status for new fetch
        }
        if raw_item_data.get('scraped_at_iso'):
            try:
                scraped_at_str = raw_item_data['scraped_at_iso']
                if 'Z' in scraped_at_str.upper():
                     source_defaults['last_scraped_at'] = datetime.fromisoformat(scraped_at_str.replace('Z', '+00:00'))
                else:
                     source_defaults['last_scraped_at'] = datetime.fromisoformat(scraped_at_str).replace(tzinfo=dt_timezone.utc)
            except (ValueError, TypeError):
                source_defaults['last_scraped_at'] = django_timezone.now() # Fallback
        else:
            source_defaults['last_scraped_at'] = django_timezone.now()

        try:
            # Using original_url as the unique identifier for a VideoSource instance
            video_source_obj, source_created = VideoSource.objects.update_or_create(
                original_url=original_url,
                defaults=source_defaults
            )
            if source_created:
                logger.info(f"CREATED new VideoSource (ID: {video_source_obj.id}) for URL: {video_source_obj.original_url}")
            else: # Existing VideoSource, update fields.
                logger.info(f"FOUND existing VideoSource (ID: {video_source_obj.id}) for URL: {video_source_obj.original_url}. Updating...")
                # If updating an existing source, we might want to reset its analysis status
                # if the scraped data is newer, indicating potential content changes.
                # For now, update_or_create handles field updates. We manually reset status for re-analysis.
                video_source_obj.processing_status = 'metadata_fetched' 
                video_source_obj.meta_visual_processing_status = 'pending'
                video_source_obj.processing_error_message = None # Clear previous errors
                video_source_obj.meta_visual_processing_error = None
                video_source_obj.last_analyzed_at = None # Force re-analysis
                video_source_obj.last_visual_indexed_at = None
                # Update other fields based on new data from source_defaults
                for key, value in source_defaults.items():
                    if value is not None and getattr(video_source_obj, key) != value:
                        setattr(video_source_obj, key, value)
                video_source_obj.save()
                logger.info(f"UPDATED existing VideoSource (ID: {video_source_obj.id}). Status reset for re-analysis.")
            return video_source_obj
        except Exception as e:
            logger.error(f"Database error creating/updating VideoSource for URL {original_url}: {e}", exc_info=True)
            return None


    def execute_search(self, search_parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main orchestration logic for a search query.
        `search_parameters` from Celery task: query_text, query_image_path, query_video_url, applied_filters, user_id, session_id.
        Returns a dictionary to update the SearchTask model.
        """
        start_time = django_timezone.now()
        logger.info(f"Orchestrator: Executing search for STID {self.papri_search_task_id}. Start: {start_time.isoformat()}. Params: {str(search_parameters)[:300]}...")
        self._update_search_task_status('processing', progress_percent=5, clear_error=True)
        
        user_prefs = None # Placeholder for user preferences logic via MemoryModule or UserProfile
        # if search_parameters.get('user_id'):
        #     user_prefs = self.memory.get_user_preference("search_settings", default={})

        # --- Stage 1: Query Understanding ---
        logger.info(f"STID {self.papri_search_task_id}: Stage 1 - Query Understanding...")
        self._update_search_task_status('processing', progress_percent=10)
        
        processed_query_data: Optional[Dict[str, Any]] = None
        query_text = search_parameters.get('query_text')
        query_image_path = search_parameters.get('query_image_path') # Full path from Celery task
        query_video_url = search_parameters.get('query_video_url')

        try:
            if query_video_url:
                processed_query_data = self.q_agent.process_video_url_query(query_video_url, query_text)
            elif query_text and query_image_path:
                processed_query_data = self.q_agent.process_hybrid_query(query_text, query_image_path)
            elif query_text:
                processed_query_data = self.q_agent.process_text_query(query_text)
            elif query_image_path:
                processed_query_data = self.q_agent.process_image_query(query_image_path)
            else:
                raise ValueError("No valid query input (text, image, or video URL) provided.")

            if not processed_query_data or processed_query_data.get("error"):
                raise ValueError(processed_query_data.get("error", "Query understanding returned an unspecified error."))
            
            self.memory.update_short_term_context("processed_query", processed_query_data) # Store for potential later use in session
            logger.info(f"STID {self.papri_search_task_id}: QAgent successful. Intent: {processed_query_data.get('intent')}. Type: {processed_query_data.get('query_type')}")
            self._update_search_task_status('processing', progress_percent=20)
        except ValueError as ve: # Catch specific validation errors
            logger.error(f"STID {self.papri_search_task_id}: QAgent validation error: {ve}", exc_info=True)
            self._update_search_task_status('failed', error_message=f"Query Input Error: {str(ve)}")
            return {"error": str(ve), "search_status_overall": "failed"}
        except Exception as e:
            logger.error(f"STID {self.papri_search_task_id}: QAgent critical error: {e}", exc_info=True)
            self._update_search_task_status('failed', error_message=f"Query Understanding Failed: {str(e)[:100]}")
            return {"error": "Query understanding stage failed.", "search_status_overall": "failed"}


        # --- Stage 2: Source Orchestration & Interfacing ---
        logger.info(f"STID {self.papri_search_task_id}: Stage 2 - Source Orchestration...")
        self._update_search_task_status('processing', progress_percent=25)
        raw_video_items_from_soi: List[Dict[str, Any]] = []
        try:
            # Determine if SOIAgent needs to run based on intent
            intent = processed_query_data.get('intent', 'general_video_search')
            if intent == "analyze_specific_video" and processed_query_data.get('original_video_url'):
                single_video_details = self.so_agent.fetch_specific_video_details(processed_query_data['original_video_url'])
                if single_video_details and not single_video_details.get("warning"): # Assuming success if no warning
                    raw_video_items_from_soi.append(single_video_details)
            # Avoid extensive fetching if intent is to search existing visual index or very specific internal task
            elif intent not in ["visual_similarity_search_only_internal", "edit_video_from_url_instructions"]: 
                raw_video_items_from_soi = self.so_agent.fetch_content_from_sources(processed_query_data)
            
            logger.info(f"STID {self.papri_search_task_id}: SOIAgent fetched {len(raw_video_items_from_soi)} raw video items.")
            self._update_search_task_status('processing', progress_percent=45)
        except Exception as e:
            logger.error(f"STID {self.papri_search_task_id}: SOIAgent critical error: {e}", exc_info=True)
            self._update_search_task_status('failed', error_message=f"Source Fetching Failed: {str(e)[:100]}")
            # Depending on severity, might still proceed to search existing index if `raw_video_items_from_soi` is empty.
            # For now, let's assume if SOIAgent fails critically, we might not have new content but can still search index.


        # --- Stage 3: Persist Basic Video Info & Content Analysis (for newly fetched items) ---
        # This stage is for items newly fetched by SOIAgent.
        analyzed_count = 0
        persisted_video_sources_for_rar: List[VideoSource] = [] # List of Django VideoSource objects

        if raw_video_items_from_soi:
            logger.info(f"STID {self.papri_search_task_id}: Stage 3 - Persistence & Content Analysis for {len(raw_video_items_from_soi)} items...")
            self._update_search_task_status('processing', progress_percent=50)
            
            for i, raw_item_data in enumerate(raw_video_items_from_soi):
                try:
                    video_source_obj = self._persist_raw_video_item(raw_item_data, search_parameters.get('user_id'))
                    if not video_source_obj:
                        logger.warning(f"STID {self.papri_search_task_id}: Failed to persist raw_item, skipping analysis: {str(raw_item_data)[:100]}")
                        continue
                    
                    persisted_video_sources_for_rar.append(video_source_obj)

                    # Determine if fresh analysis is needed by CAAgent.
                    # CAAgent itself should also have logic to check if analysis is stale or incomplete.
                    # For simplicity here, assume new/updated items always trigger CAAgent.
                    # CAAgent.analyze_video_content will update video_source_obj's status.
                    logger.debug(f"STID {self.papri_search_task_id}: Triggering CAAgent for VSID {video_source_obj.id} ({i+1}/{len(raw_video_items_from_soi)})")
                    analysis_report = self.ca_agent.analyze_video_content(video_source_obj, raw_item_data)
                    logger.debug(f"STID {self.papri_search_task_id}: CAAgent report for VSID {video_source_obj.id}: {analysis_report}")
                    if not analysis_report.get("errors"):
                        analyzed_count += 1
                    
                    current_progress_stage3 = 50 + int(((i + 1) / len(raw_video_items_from_soi)) * 30) # This stage is ~30% of time
                    self._update_search_task_status('processing', progress_percent=current_progress_stage3)
                except Exception as e_persist_analyze: # Catch errors during loop for one item
                    logger.error(f"STID {self.papri_search_task_id}: Error persisting/analyzing item {str(raw_item_data)[:100]}: {e_persist_analyze}", exc_info=True)
                    # Log this error to SearchTask but continue with other items
                    self._update_search_task_status('processing', error_message=f"Item processing error: {str(e_persist_analyze)[:50]}.")
            
            logger.info(f"STID {self.papri_search_task_id}: Stage 3 complete. Persisted {len(persisted_video_sources_for_rar)} sources. Attempted analysis for {analyzed_count} of them.")
        else:
            logger.info(f"STID {self.papri_search_task_id}: Stage 3 - No new items from SOIAgent to persist/analyze.")
        
        self._update_search_task_status('processing', progress_percent=85)


        # --- Stage 4: Result Aggregation & Ranking ---
        logger.info(f"STID {self.papri_search_task_id}: Stage 4 - Result Aggregation & Ranking...")
        final_ranked_results_for_task: List[Dict[str, Any]] = []
        try:
            final_ranked_results_for_task = self.ra_agent.aggregate_and_rank_results(
                processed_query_data=processed_query_data,
                user_filters=search_parameters.get('applied_filters', {}),
                user_preferences=user_prefs
            )
            logger.info(f"STID {self.papri_search_task_id}: RARAgent processing complete. Found {len(final_ranked_results_for_task)} potential results.")
        except Exception as e:
            logger.error(f"STID {self.papri_search_task_id}: RARAgent critical error: {e}", exc_info=True)
            self._update_search_task_status('failed', error_message=f"Result Aggregation Failed: {str(e)[:100]}")
            return {"error": "Result aggregation stage failed.", "search_status_overall": "failed"}

        self._update_search_task_status('completed', progress_percent=100)

        # Prepare final output for the SearchTask model
        ranked_canonical_video_ids = [item['video_id'] for item in final_ranked_results_for_task if 'video_id' in item]

        final_status_message = "Search complete."
        if not final_ranked_results_for_task:
            final_status_message = "Search complete. No results found matching your query criteria."
            if not raw_video_items_from_soi and not analyzed_count: # No new items and no results from index
                 logger.info(f"STID {self.papri_search_task_id}: No new items were fetched/analyzed, and RARAgent found no matches in existing index.")


        end_time = django_timezone.now()
        duration = end_time - start_time
        logger.info(f"Orchestrator: Search execution for STID {self.papri_search_task_id} FINISHED. Duration: {duration.total_seconds():.2f}s. Status: {final_status_message}")
        
        return {
            "message": final_status_message,
            "search_status_overall": "completed", # Can be 'partial_results' if RARAgent indicates it
            "items_fetched_from_sources": len(raw_video_items_from_soi),
            "items_processed_for_analysis": analyzed_count, # Items for which CAAgent was triggered
            "ranked_video_count": len(ranked_canonical_video_ids),
            "persisted_video_ids_ranked": ranked_canonical_video_ids, 
            "results_data_detailed": final_ranked_results_for_task 
        }
