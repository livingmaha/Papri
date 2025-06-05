# backend/ai_agents/main_orchestrator.py
import logging
import os
from datetime import datetime, timedelta # Ensure timedelta is imported
from typing import Dict, Any, List, Optional
import traceback # For detailed error logging

from django.conf import settings
from django.utils import timezone as django_timezone
from django.db import transaction

from api.models import SearchTask, Video, VideoSource, UserProfile # Assuming UserProfile for user_prefs
from .query_understanding_agent import QueryUnderstandingAgent
from .source_orchestration_agent import SourceOrchestrationAgent, SourceOrchestrationError # Custom error
from .content_analysis_agent import ContentAnalysisAgent, ContentAnalysisError # Custom error
from .result_aggregation_agent import ResultAggregationAgent, ResultAggregationError # Custom error
from .memory_module import MemoryModule
from .utils import generate_deduplication_hash, normalize_text_unicode

logger = logging.getLogger(__name__)

# Define custom exceptions for agent stages if not already in respective agent files
class OrchestratorError(Exception):
    """Base class for orchestrator specific errors."""
    pass

class QueryUnderstandingError(OrchestratorError):
    """Error during query understanding phase."""
    pass


class PapriAIAgentOrchestrator:
    def __init__(self, papri_search_task_id: str):
        self.papri_search_task_id = papri_search_task_id
        self.q_agent = QueryUnderstandingAgent()
        self.so_agent = SourceOrchestrationAgent()
        self.ca_agent = ContentAnalysisAgent()
        self.ra_agent = ResultAggregationAgent()
        self.memory = MemoryModule(session_id=str(papri_search_task_id))
        logger.info(f"PapriAIAgentOrchestrator initialized for STID: {self.papri_search_task_id}")

    def _update_search_task(self, status: str, error_message: Optional[str] = None, 
                              progress_percent: Optional[int] = None, 
                              clear_error: bool = False,
                              **extra_fields_to_update):
        """
        Helper to update the SearchTask model instance atomically.
        Ensures error messages are appended unless cleared.
        """
        try:
            with transaction.atomic():
                task = SearchTask.objects.select_for_update().get(id=self.papri_search_task_id)
                task.status = status
                
                if clear_error:
                    task.error_message = None
                elif error_message:
                    existing_error = task.error_message or ""
                    if existing_error and not existing_error.endswith(". "): existing_error += ". "
                    # Prepend new error for visibility, keep total length manageable
                    new_error_message = f"{error_message}. {existing_error}"
                    task.error_message = new_error_message[:1000]

                if progress_percent is not None:
                    # Assuming SearchTask has a progress field, e.g., task.progress_percent
                    if hasattr(task, 'progress_percent'): # Check if field exists
                        task.progress_percent = min(max(0, progress_percent), 100)
                
                for field, value in extra_fields_to_update.items():
                    if hasattr(task, field):
                        setattr(task, field, value)
                    else:
                        logger.warning(f"STID {task.id}: Attempted to update non-existent field '{field}' on SearchTask.")
                
                task.updated_at = django_timezone.now()
                update_fields = ['status', 'updated_at']
                if error_message or clear_error: update_fields.append('error_message')
                if progress_percent is not None and hasattr(task, 'progress_percent'): update_fields.append('progress_percent')
                update_fields.extend(extra_fields_to_update.keys())
                
                task.save(update_fields=list(set(update_fields))) # Ensure unique fields
            logger.debug(f"SearchTask {self.papri_search_task_id} status set to: {status}. Progress: {progress_percent}%. Error: {task.error_message if hasattr(task,'error_message') else 'N/A'}")
        except SearchTask.DoesNotExist:
            logger.critical(f"STID {self.papri_search_task_id}: SearchTask not found for status update. This is a critical error.")
        except Exception as e:
            logger.error(f"STID {self.papri_search_task_id}: Error updating SearchTask status: {e}", exc_info=True)

    @transaction.atomic
    def _persist_raw_video_item(self, raw_item_data: Dict[str, Any], search_task_user_id: Optional[int]) -> Optional[VideoSource]:
        # (Content of _persist_raw_video_item from your uploaded file can be kept mostly as-is)
        # ... I will assume the previous version of this method is here ...
        # Key change: ensure it logs errors clearly if persistence fails for an item.
        title = raw_item_data.get('title')
        original_url = raw_item_data.get('original_url')
        platform_name = raw_item_data.get('platform_name')
        platform_video_id = raw_item_data.get('platform_video_id')

        if not all([title, original_url, platform_name, platform_video_id]):
            logger.warning(f"STID {self.papri_search_task_id}: Skipping persistence for raw item due to missing critical fields: {str(raw_item_data)[:200]}")
            return None
        
        normalized_title = normalize_text_unicode(title)[:499]
        duration_seconds = raw_item_data.get('duration_seconds')
        dedupe_hash = generate_deduplication_hash(normalized_title, duration_seconds)

        video_defaults = {
            'title': normalized_title,
            'description': raw_item_data.get('description'),
            'duration_seconds': duration_seconds,
            'tags': raw_item_data.get('tags', []),
            'category': raw_item_data.get('category'),
            'primary_thumbnail_url': raw_item_data.get('thumbnail_url'), # Persist initial thumbnail
        }
        if raw_item_data.get('publication_date_iso'):
            try:
                pub_date_str = raw_item_data['publication_date_iso']
                video_defaults['publication_date'] = django_timezone.make_aware(datetime.fromisoformat(pub_date_str.replace('Z', ''))) if 'Z' in pub_date_str else datetime.fromisoformat(pub_date_str)
            except (ValueError, TypeError): pass
        
        try:
            canonical_video, video_created = Video.objects.update_or_create(deduplication_hash=dedupe_hash, defaults=video_defaults)
            if video_created: logger.info(f"STID {self.papri_search_task_id}: CREATED Canonical Video ID {canonical_video.id}")
        except Exception as e_vid:
            logger.error(f"STID {self.papri_search_task_id}: DB error on Video for hash {dedupe_hash}: {e_vid}", exc_info=True)
            return None # Critical error for this item

        source_defaults = {
            'video': canonical_video, 'platform_name': platform_name, 'platform_video_id': platform_video_id,
            'embed_url': raw_item_data.get('embed_url'), 'thumbnail_url': raw_item_data.get('thumbnail_url'),
            'uploader_name': raw_item_data.get('uploader_name'), 'uploader_url': raw_item_data.get('uploader_url'),
            'view_count': raw_item_data.get('view_count'), 'like_count': raw_item_data.get('like_count'),
            'comment_count': raw_item_data.get('comment_count'),
            'processing_status': 'metadata_fetched', 'meta_visual_processing_status': 'pending',
            'last_scraped_at': django_timezone.make_aware(datetime.fromisoformat(raw_item_data['scraped_at_iso'].replace('Z', ''))) if raw_item_data.get('scraped_at_iso') else django_timezone.now(),
            'source_metadata_json': raw_item_data # Store the whole raw item for now for CAAgent
        }
        try:
            video_source_obj, source_created = VideoSource.objects.update_or_create(original_url=original_url, defaults=source_defaults)
            if source_created: logger.info(f"STID {self.papri_search_task_id}: CREATED VideoSource ID {video_source_obj.id} for URL {original_url}")
            else: # Reset status for re-analysis if updating
                video_source_obj.processing_status = 'metadata_fetched'
                video_source_obj.meta_visual_processing_status = 'pending'
                video_source_obj.processing_error_message = None
                video_source_obj.meta_visual_processing_error = None
                video_source_obj.save(update_fields=['processing_status', 'meta_visual_processing_status', 'processing_error_message', 'meta_visual_processing_error'])
                logger.info(f"STID {self.papri_search_task_id}: UPDATED VideoSource ID {video_source_obj.id}, reset status for re-analysis.")
            return video_source_obj
        except Exception as e_vs:
            logger.error(f"STID {self.papri_search_task_id}: DB error on VideoSource for URL {original_url}: {e_vs}", exc_info=True)
            return None


    def execute_search(self, search_parameters: Dict[str, Any]) -> Dict[str, Any]:
        start_time = django_timezone.now()
        logger.info(f"Orchestrator: Executing search for STID {self.papri_search_task_id}. Start: {start_time.isoformat()}. Params: {str(search_parameters)[:250]}...")
        self._update_search_task(status='processing', progress_percent=5, clear_error=True)
        
        user_prefs = None # Simplified

        # --- Stage 1: Query Understanding ---
        processed_query_data: Optional[Dict[str, Any]] = None
        try:
            self._update_search_task(status='processing_query_understanding', progress_percent=10) # New status
            query_text = search_parameters.get('query_text')
            query_image_path = search_parameters.get('query_image_path')
            query_video_url = search_parameters.get('query_video_url')

            if query_video_url:
                processed_query_data = self.q_agent.process_video_url_query(query_video_url, query_text)
            elif query_text and query_image_path:
                processed_query_data = self.q_agent.process_hybrid_query(query_text, query_image_path)
            elif query_text:
                processed_query_data = self.q_agent.process_text_query(query_text)
            elif query_image_path:
                processed_query_data = self.q_agent.process_image_query(query_image_path)
            else:
                raise QueryUnderstandingError("No valid query input provided.")

            if not processed_query_data or processed_query_data.get("error"):
                raise QueryUnderstandingError(processed_query_data.get("error", "QAgent returned unspecified error."))
            
            self.memory.update_short_term_context("processed_query", processed_query_data)
            logger.info(f"STID {self.papri_search_task_id}: QAgent success. Intent: {processed_query_data.get('intent')}")
        except QueryUnderstandingError as qe:
            err_msg = f"Query Understanding Failed: {str(qe)}"
            logger.error(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_query_understanding', error_message=err_msg)
            return {"error": err_msg, "search_status_overall": "failed_query_understanding"}
        except Exception as e: # Catch-all for unexpected QAgent errors
            err_msg = f"Unexpected QAgent Error: {str(e)}"
            logger.critical(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_query_understanding', error_message=err_msg)
            return {"error": err_msg, "search_status_overall": "failed_query_understanding"}

        # --- Stage 2: Source Orchestration & Interfacing ---
        raw_video_items_from_soi: List[Dict[str, Any]] = []
        try:
            self._update_search_task(status='processing_sources', progress_percent=25)
            intent = processed_query_data.get('intent', 'general_video_search')
            if intent == "analyze_specific_video" and processed_query_data.get('original_video_url'):
                # SOIAgent should handle its own errors and log them.
                # If it returns None or an empty list, it indicates failure or no data.
                single_video_details = self.so_agent.fetch_specific_video_details(processed_query_data['original_video_url'])
                if single_video_details and not single_video_details.get("warning"):
                    raw_video_items_from_soi.append(single_video_details)
            elif intent not in ["visual_similarity_search_only_internal", "edit_video_from_url_instructions"]: 
                raw_video_items_from_soi = self.so_agent.fetch_content_from_sources(processed_query_data)
            
            if self.so_agent.encountered_errors: # Assume SOAgent sets a flag or returns error list
                 self._update_search_task(status='processing_sources', error_message="Partial errors in source fetching.") # Non-critical error
            logger.info(f"STID {self.papri_search_task_id}: SOIAgent fetched {len(raw_video_items_from_soi)} items.")
        except SourceOrchestrationError as soe: # Custom error from SOIAgent
            err_msg = f"Source Fetching Failed Critically: {str(soe)}"
            logger.error(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_source_fetch', error_message=err_msg)
            # Decide if we can proceed to RARAgent with empty list or if it's a hard fail.
            # For now, let's allow RARAgent to search existing index.
        except Exception as e:
            err_msg = f"Unexpected SOIAgent Error: {str(e)}"
            logger.critical(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_source_fetch', error_message=err_msg)
            # Continue to allow RARAgent to search existing index.

        # --- Stage 3: Persist & Content Analysis (for newly fetched items) ---
        self._update_search_task(status='processing_content_analysis', progress_percent=50) # New status
        analyzed_count = 0
        items_with_analysis_errors = 0
        if raw_video_items_from_soi:
            logger.info(f"STID {self.papri_search_task_id}: Stage 3 - Persist & Analyze {len(raw_video_items_from_soi)} items...")
            for i, raw_item in enumerate(raw_video_items_from_soi):
                video_source_obj = self._persist_raw_video_item(raw_item, search_parameters.get('user_id'))
                if not video_source_obj:
                    self._update_search_task(status='processing_content_analysis', error_message=f"Failed to persist item: {str(raw_item)[:100]}.")
                    items_with_analysis_errors += 1
                    continue
                try:
                    # CAAgent updates VideoSource status internally
                    analysis_report = self.ca_agent.analyze_video_content(video_source_obj, raw_item)
                    if analysis_report.get("errors") or "failed" in analysis_report.get("final_status_set", "") :
                        items_with_analysis_errors +=1
                        # Errors logged by CAAgent and potentially on VideoSource model
                        self._update_search_task(status='processing_content_analysis', error_message=f"Analysis error for VSID {video_source_obj.id}.")
                    else:
                        analyzed_count += 1
                except ContentAnalysisError as cae:
                    logger.error(f"STID {self.papri_search_task_id}: CAAgent error for VSID {video_source_obj.id}: {cae}", exc_info=True)
                    self._update_search_task(status='processing_content_analysis', error_message=f"Content Analysis Error (VSID {video_source_obj.id}): {str(cae)[:100]}.")
                    items_with_analysis_errors += 1
                except Exception as e_ca_loop: # Catch-all for this item
                    logger.error(f"STID {self.papri_search_task_id}: Unexpected CAAgent loop error for VSID {video_source_obj.id}: {e_ca_loop}", exc_info=True)
                    self._update_search_task(status='processing_content_analysis', error_message=f"Unexpected CA Loop Error (VSID {video_source_obj.id}).")
                    items_with_analysis_errors += 1
                
                prog = 50 + int(((i + 1) / len(raw_video_items_from_soi)) * 30)
                self._update_search_task(status='processing_content_analysis', progress_percent=prog)
            
            if items_with_analysis_errors == len(raw_video_items_from_soi) and raw_video_items_from_soi: # All new items failed analysis
                self._update_search_task(status='failed_content_analysis', error_message="All new items failed content analysis.")
                # This is serious, but RARAgent might still find results from existing index.
        else:
            logger.info(f"STID {self.papri_search_task_id}: No new items from SOIAgent to analyze.")

        # --- Stage 4: Result Aggregation & Ranking ---
        final_ranked_results_for_task: List[Dict[str, Any]] = []
        try:
            self._update_search_task(status='aggregating_results', progress_percent=85) # New status
            final_ranked_results_for_task = self.ra_agent.aggregate_and_rank_results(
                processed_query_data=processed_query_data,
                user_filters=search_parameters.get('applied_filters', {}),
                user_preferences=user_prefs
            )
            logger.info(f"STID {self.papri_search_task_id}: RARAgent found {len(final_ranked_results_for_task)} results.")
        except ResultAggregationError as rae:
            err_msg = f"Result Aggregation Failed: {str(rae)}"
            logger.error(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_aggregation', error_message=err_msg)
            return {"error": err_msg, "search_status_overall": "failed_aggregation"}
        except Exception as e:
            err_msg = f"Unexpected RARAgent Error: {str(e)}"
            logger.critical(f"STID {self.papri_search_task_id}: {err_msg}", exc_info=True)
            self._update_search_task(status='failed_aggregation', error_message=err_msg)
            return {"error": err_msg, "search_status_overall": "failed_aggregation"}

        # --- Finalize SearchTask ---
        final_task_status = 'completed'
        final_message = "Search complete."
        if items_with_analysis_errors > 0 and not final_ranked_results_for_task:
            final_task_status = 'failed_content_analysis' # If analysis errors prevented any results
            final_message = "Search completed, but content analysis issues were encountered for all new items and no existing results found."
        elif items_with_analysis_errors > 0:
            final_task_status = 'partial_results' # Some new items failed, but existing results might be fine
            final_message = "Search complete. Some new items had analysis issues. Results may be from existing index or partially processed items."
            self._update_search_task(status=final_task_status, error_message="Partial content analysis failures.")
        elif not final_ranked_results_for_task:
            final_message = "Search complete. No results found matching your query criteria."
            # Status remains 'completed' but results are empty.
        
        self._update_search_task(
            status=final_task_status, 
            progress_percent=100,
            result_video_ids_json=[item['video_id'] for item in final_ranked_results_for_task if 'video_id' in item],
            detailed_results_info_json=final_ranked_results_for_task
        )
        
        end_time = django_timezone.now()
        duration = end_time - start_time
        logger.info(f"Orchestrator: STID {self.papri_search_task_id} FINISHED. Duration: {duration.total_seconds():.2f}s. Final Status: {final_task_status}")
        
        return {
            "message": final_message,
            "search_status_overall": final_task_status,
            "items_fetched_from_sources": len(raw_video_items_from_soi),
            "items_processed_for_analysis": analyzed_count,
            "ranked_video_count": len(final_ranked_results_for_task),
            "persisted_video_ids_ranked": [item['video_id'] for item in final_ranked_results_for_task if 'video_id' in item], 
            "results_data_detailed": final_ranked_results_for_task 
        }
