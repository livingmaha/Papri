# backend/api/tasks.py
import logging
import os
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from django.db import transaction
import requests # For retry example for ConnectionError
import yt_dlp # For retry example for DownloadError

from .models import SearchTask, EditTask, VideoSource, Video
from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator
from backend.ai_agents.ai_video_editor_agent import AIVideoEditorAgent

logger = logging.getLogger(__name__)

class TaskOperationalError(Exception):
    """Custom exception for known operational errors that might not warrant a retry."""
    pass

@shared_task(bind=True, name='api.process_search_query_task', max_retries=2, default_retry_delay=60, queue='ai_processing')
def process_search_query_task(self, search_task_id):
    # (Content from previous refinement for process_search_query_task is kept as is)
    logger.info(f"[Celery TASK START - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Celery Task ID: {self.request.id}")
    search_task = None 
    try:
        with transaction.atomic(): 
            search_task = SearchTask.objects.select_for_update().get(id=search_task_id) 
            if search_task.status not in ['pending', 'queued', 'failed_timeout']: 
                 logger.warning(f"SearchTask STID {search_task_id} already in status '{search_task.status}'. Skipping execution.")
                 return {"status": search_task.status, "message": "Task already processed or in an unretryable state."}
            search_task.status = 'processing_query_understanding' # More specific initial processing status
            search_task.celery_task_id = self.request.id
            search_task.error_message = None 
            search_task.save(update_fields=['status', 'celery_task_id', 'error_message', 'updated_at'])
        logger.debug(f"SearchTask STID {search_task_id} status updated to 'processing_query_understanding'.")
        full_image_path = None
        if search_task.query_image_ref:
            if not search_task.query_image_ref.startswith(('http://', 'https://')):
                 full_image_path = os.path.join(settings.MEDIA_ROOT, search_task.query_image_ref)
            else: full_image_path = search_task.query_image_ref
        search_parameters = {
            'query_text': search_task.query_text, 'query_image_path': full_image_path,
            'query_video_url': search_task.query_video_url, 'applied_filters': search_task.applied_filters_json or {},
            'user_id': str(search_task.user_id) if search_task.user else None, 'session_id': search_task.session_id,
            'search_task_model_id': str(search_task.id)
        }
        logger.debug(f"Initializing PapriAIAgentOrchestrator for STID: {search_task_id} with params: {str(search_parameters)[:500]}")
        orchestrator = PapriAIAgentOrchestrator(papri_search_task_id=search_task_id)
        results_data = orchestrator.execute_search(search_parameters) # Orchestrator now handles internal status updates
        logger.debug(f"Orchestrator finished for STID: {search_task_id}. Raw results_data: {str(results_data)[:500]}...")
        with transaction.atomic(): # Final update, re-fetch to ensure latest status from orchestrator
            search_task = SearchTask.objects.select_for_update().get(id=search_task_id)
            # If orchestrator set a final status, respect it. Otherwise, use its return.
            if search_task.status not in ['completed', 'partial_results', 'failed', 'failed_query_understanding', 'failed_source_fetch', 'failed_content_analysis', 'failed_aggregation']:
                search_task.status = results_data.get("search_status_overall", 'failed' if "error" in results_data else 'completed')
            if "error" in results_data and not search_task.error_message: # Only set if orchestrator didn't already
                search_task.error_message = str(results_data["error"])[:1000]
            if search_task.status in ['completed', 'partial_results']:
                search_task.result_video_ids_json = results_data.get("persisted_video_ids_ranked", [])
                search_task.detailed_results_info_json = results_data.get("results_data_detailed", [])
                if search_task.status == 'completed': search_task.error_message = None # Clear error if fully completed
            search_task.updated_at = timezone.now()
            search_task.save()
        logger.info(f"[Celery TASK END - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Final Status: {search_task.status}")
        return {"status": search_task.status, "search_task_id": str(search_task_id), "message": "Search processing finished."}
    except SearchTask.DoesNotExist:
        logger.error(f"SearchTask STID {search_task_id} not found. No retry.")
        return {"status": "error_task_not_found", "search_task_id": str(search_task_id), "message": "SearchTask not found."}
    except TaskOperationalError as toe:
        logger.error(f"TaskOperationalError in process_search_query_task for STID {search_task_id}: {toe}", exc_info=True)
        if search_task:
            with transaction.atomic():
                search_task = SearchTask.objects.select_for_update().get(id=search_task_id)
                search_task.status = 'failed'; search_task.error_message = f"Operational Error: {str(toe)[:500]}"
                search_task.save(update_fields=['status', 'error_message', 'updated_at'])
        return {"status": "failed_operational", "search_task_id": str(search_task_id), "message": str(toe)}
    except Exception as e:
        logger.error(f"Unhandled exception in process_search_query_task for STID {search_task_id}: {e}", exc_info=True)
        if search_task:
            with transaction.atomic():
                search_task = SearchTask.objects.select_for_update().get(id=search_task_id)
                search_task.status = 'failed'; search_task.error_message = f"Task Execution Error: {str(e)[:500]}"
                search_task.save(update_fields=['status', 'error_message', 'updated_at'])
        default_retry_delay = self.default_retry_delay if hasattr(self, 'default_retry_delay') else 60
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            logger.warning(f"Network-related error for STID {search_task_id}. Retrying.")
            raise self.retry(exc=e, countdown=int(default_retry_delay * (2 ** self.request.retries)))
        elif self.request.retries < self.max_retries:
             logger.warning(f"Unhandled error for STID {search_task_id}. Retrying.")
             raise self.retry(exc=e)
        return {"status": "failed_exception", "search_task_id": str(search_task_id), "message": "Unhandled exception during task execution."}


@shared_task(bind=True, name='api.process_video_edit_task', max_retries=1, default_retry_delay=120, queue='video_editing')
def process_video_edit_task(self, edit_task_id):
    logger.info(f"[Celery TASK START - Q:video_editing] process_video_edit_task for EditTask ID: {edit_task_id}. Celery Task ID: {self.request.id}")
    edit_task = None
    try:
        with transaction.atomic():
            edit_task = EditTask.objects.select_for_update().get(id=edit_task_id)
            # Check if task is already completed or terminally failed by another process/previous run
            if edit_task.status not in ['pending', 'queued', 
                                        'downloading_video', 'interpreting_prompt', 'editing_in_progress', # Allow re-entry if stuck mid-process
                                        'failed_download', 'failed_prompt_interpretation', 'failed_editing', 'failed_timeout']: # Allow retry on some failures
                logger.warning(f"EditTask ETID {edit_task_id} already in status '{edit_task.status}'. Skipping further processing.")
                return {"status": edit_task.status, "message": "Task already processed or in an unretryable terminal state."}

            # Initial status for this run
            edit_task.status = 'queued' # Celery picked it up, about to process
            edit_task.celery_task_id = self.request.id
            edit_task.error_message = None # Clear previous errors for a new attempt
            edit_task.save(update_fields=['status', 'celery_task_id', 'error_message', 'updated_at'])
        logger.debug(f"EditTask ETID {edit_task_id} status updated to 'queued' by Celery worker.")

        video_editor_agent = AIVideoEditorAgent()
        project = edit_task.project # Already select_related in view

        input_video_path_or_url = None
        # (Logic to determine input_video_path_or_url as before)
        if project.original_video_source and project.original_video_source.original_url:
            input_video_path_or_url = project.original_video_source.original_url
        elif project.uploaded_video_path:
            if not project.uploaded_video_path.startswith(('http://', 'https://')):
                input_video_path_or_url = os.path.join(settings.MEDIA_ROOT, project.uploaded_video_path)
            else: input_video_path_or_url = project.uploaded_video_path
        else:
            # This is a setup error, non-retryable by Celery, handled by TaskOperationalError
            raise TaskOperationalError("No video source specified for editing in the project.")
        
        # The AIVideoEditorAgent's perform_edit method is now responsible for updating EditTask status
        # throughout its lifecycle (downloading_video, interpreting_prompt, editing_in_progress, etc.)
        # and for setting the final status ('completed', 'failed_download', 'failed_editing', etc.).
        edit_result = video_editor_agent.perform_edit(
            video_path_or_url=input_video_path_or_url,
            prompt=edit_task.prompt_text,
            edit_task_id_for_agent=str(edit_task.id)
        )
        logger.debug(f"AIVideoEditorAgent returned for ETID {edit_task_id}: {edit_result}")

        # Final check and update based on agent's return, though agent should have updated DB.
        # This ensures Celery task reflects the outcome.
        with transaction.atomic():
            edit_task = EditTask.objects.select_for_update().get(id=edit_task_id) # Re-fetch latest
            
            # Trust the status set by the agent via _update_edit_task_status.
            # If agent failed to set a terminal status, use its return value.
            if edit_task.status not in ['completed', 'failed_download', 'failed_prompt_interpretation', 'failed_editing', 'failed_output_storage', 'failed']:
                final_status_from_agent = edit_result.get('final_task_status', 'failed' if 'error' in edit_result else 'completed')
                edit_task.status = final_status_from_agent
                if final_status_from_agent == 'completed' and 'output_media_path' in edit_result:
                    edit_task.result_media_path = edit_result['output_media_path']
                    edit_task.error_message = None
                elif 'error' in edit_result and not edit_task.error_message: # Only set if agent didn't
                    edit_task.error_message = str(edit_result['error'])[:1000]
                edit_task.updated_at = timezone.now()
                edit_task.save()
            
            elif edit_task.status == 'completed' and 'output_media_path' in edit_result and not edit_task.result_media_path:
                 # If agent set completed but somehow path wasn't saved by it.
                 edit_task.result_media_path = edit_result['output_media_path']
                 edit_task.save(update_fields=['result_media_path', 'updated_at'])
        
        logger.info(f"[Celery TASK END - Q:video_editing] process_video_edit_task for ETID: {edit_task_id}. Final DB Status: {edit_task.status}")
        return {"status": edit_task.status, "edit_task_id": str(edit_task_id), "message": "Video edit processing cycle finished."}

    except EditTask.DoesNotExist:
        logger.error(f"EditTask ETID {edit_task_id} not found. No retry.")
        return {"status": "error_task_not_found", "edit_task_id": str(edit_task_id), "message": "EditTask not found."}
    except TaskOperationalError as toe:
        logger.error(f"TaskOperationalError in process_video_edit_task for ETID {edit_task_id}: {toe}", exc_info=False) # No need for full trace for this
        if edit_task: # edit_task might be None if DoesNotExist happened before assignment
            with transaction.atomic():
                edit_task = EditTask.objects.select_for_update().get(id=edit_task_id) # Re-fetch
                edit_task.status = 'failed' # Or a more specific 'failed_input_data' if added to choices
                edit_task.error_message = f"Operational Error: {str(toe)[:500]}"
                edit_task.save(update_fields=['status', 'error_message', 'updated_at'])
        return {"status": "failed_operational", "edit_task_id": str(edit_task_id), "message": str(toe)}
    except Exception as e:
        logger.error(f"Unhandled exception in process_video_edit_task for ETID {edit_task_id}: {e}", exc_info=True)
        if edit_task:
            with transaction.atomic():
                edit_task = EditTask.objects.select_for_update().get(id=edit_task_id)
                # If agent hasn't set a specific failure, set general 'failed'
                if edit_task.status not in ['failed_download', 'failed_prompt_interpretation', 'failed_editing', 'failed_output_storage']:
                    edit_task.status = 'failed'
                edit_task.error_message = (edit_task.error_message or "") + f"; Celery Task Error: {str(e)[:250]}"
                edit_task.error_message = edit_task.error_message[:1000]
                edit_task.save(update_fields=['status', 'error_message', 'updated_at'])
        
        default_retry_delay = self.default_retry_delay if hasattr(self, 'default_retry_delay') else 120
        # Retry for specific, potentially transient errors
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, yt_dlp.utils.DownloadError)) and self.request.retries < self.max_retries:
            logger.warning(f"Download/Network error for ETID {edit_task_id}. Retrying ({self.request.retries + 1}/{self.max_retries+1}).")
            raise self.retry(exc=e, countdown=int(default_retry_delay * (2 ** self.request.retries)))
        elif self.request.retries < self.max_retries: # Generic retry for other errors if retries left
             logger.warning(f"Unhandled error for ETID {edit_task_id}. Retrying ({self.request.retries + 1}/{self.max_retries+1}).")
             raise self.retry(exc=e)
        # If retries exhausted, Celery marks as failed. The DB update above should reflect this.
        return {"status": "failed_exception", "edit_task_id": str(edit_task_id), "message": "Unhandled exception during video edit execution."}
