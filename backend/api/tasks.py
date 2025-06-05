# backend/api/tasks.py
import logging
import os
from django.utils import timezone
from django.conf import settings
from celery import shared_task, Celery # Use shared_task for tasks within Django apps
from django.db import transaction # For atomic updates

# Import models
from .models import SearchTask, EditTask, VideoSource, Video # Ensure all relevant models are imported

# Import AI Agent Orchestrators/Agents
from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator # Ensure correct import path
from backend.ai_agents.ai_video_editor_agent import AIVideoEditorAgent # Ensure correct import path

logger = logging.getLogger(__name__)

# Custom Exception for specific operational errors within tasks
class TaskOperationalError(Exception):
    """Custom exception for known operational errors that might not warrant a retry."""
    pass

@shared_task(bind=True, name='api.process_search_query_task', max_retries=2, default_retry_delay=60, queue='ai_processing')
def process_search_query_task(self, search_task_id):
    logger.info(f"[Celery TASK START - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Celery Task ID: {self.request.id}")
    search_task = None # Initialize for broader scope
    try:
        with transaction.atomic(): # Wrap DB updates in a transaction
            search_task = SearchTask.objects.select_for_update().get(id=search_task_id) # Lock row
            if search_task.status not in ['pending', 'queued', 'failed_timeout']: # Allow retry on timeout
                 logger.warning(f"SearchTask STID {search_task_id} already in status '{search_task.status}'. Skipping execution.")
                 return {"status": search_task.status, "message": "Task already processed or in an unretryable state."}

            search_task.status = 'processing'
            search_task.celery_task_id = self.request.id
            search_task.error_message = None # Clear previous errors on new run
            search_task.save(update_fields=['status', 'celery_task_id', 'error_message', 'updated_at'])
        logger.debug(f"SearchTask STID {search_task_id} status updated to 'processing'.")

        full_image_path = None
        if search_task.query_image_ref:
            if not search_task.query_image_ref.startswith(('http://', 'https://')):
                 full_image_path = os.path.join(settings.MEDIA_ROOT, search_task.query_image_ref)
            else:
                full_image_path = search_task.query_image_ref

        search_parameters = {
            'query_text': search_task.query_text,
            'query_image_path': full_image_path,
            'query_video_url': search_task.query_video_url,
            'applied_filters': search_task.applied_filters_json or {},
            'user_id': str(search_task.user_id) if search_task.user else None,
            'session_id': search_task.session_id,
            'search_task_model_id': str(search_task.id)
        }
        
        logger.debug(f"Initializing PapriAIAgentOrchestrator for STID: {search_task_id} with params: {str(search_parameters)[:500]}")
        orchestrator = PapriAIAgentOrchestrator(papri_search_task_id=search_task_id) # Orchestrator will handle its own status updates
        
        # Orchestrator is expected to update the SearchTask model with detailed status and errors
        # during its execution stages.
        results_data = orchestrator.execute_search(search_parameters)
        logger.debug(f"Orchestrator finished for STID: {search_task_id}. Raw results_data: {str(results_data)[:500]}...")

        # Final status update based on orchestrator's overall outcome
        # The orchestrator should ideally set the final status on the SearchTask object itself.
        # This is a fallback / final confirmation.
        with transaction.atomic():
            search_task = SearchTask.objects.select_for_update().get(id=search_task_id) # Re-fetch and lock
            if "error" in results_data and search_task.status not in ['failed', 'failed_query_understanding', 'failed_source_fetch', 'failed_content_analysis', 'failed_aggregation']:
                logger.error(f"Orchestration reported an error for STID {search_task_id}: {results_data['error']}")
                search_task.status = results_data.get("search_status_overall", 'failed') # Use orchestrator's determined fail status
                search_task.error_message = str(results_data["error"])[:1000]
            elif search_task.status not in ['failed', 'failed_query_understanding', 'failed_source_fetch', 'failed_content_analysis', 'failed_aggregation']: # If orchestrator didn't set a fail status
                search_task.status = results_data.get("search_status_overall", 'completed')
                search_task.result_video_ids_json = results_data.get("persisted_video_ids_ranked", [])
                search_task.detailed_results_info_json = results_data.get("results_data_detailed", [])
                search_task.error_message = None
            search_task.updated_at = timezone.now()
            search_task.save()
        
        logger.info(f"[Celery TASK END - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Final Status: {search_task.status}")
        return {"status": search_task.status, "search_task_id": str(search_task_id), "message": "Search processing finished."}

    except SearchTask.DoesNotExist:
        logger.error(f"SearchTask STID {search_task_id} not found in Celery task. No retry.")
        return {"status": "error_task_not_found", "search_task_id": str(search_task_id), "message": "SearchTask not found."}
    except TaskOperationalError as toe: # Specific non-retryable operational errors
        logger.error(f"TaskOperationalError in process_search_query_task for STID {search_task_id}: {toe}", exc_info=True)
        if search_task: # search_task might be None if DoesNotExist happened before assignment
            with transaction.atomic():
                search_task = SearchTask.objects.select_for_update().get(id=search_task_id) # Re-fetch
                search_task.status = 'failed' # Or a more specific fail status
                search_task.error_message = f"Operational Error: {str(toe)[:500]}"
                search_task.save(update_fields=['status', 'error_message', 'updated_at'])
        return {"status": "failed_operational", "search_task_id": str(search_task_id), "message": str(toe)}
    except Exception as e:
        logger.error(f"Unhandled exception in process_search_query_task for STID {search_task_id}: {e}", exc_info=True)
        if search_task:
            with transaction.atomic():
                search_task = SearchTask.objects.select_for_update().get(id=search_task_id) # Re-fetch
                # Use a generic 'failed' or a more specific 'failed_uncaught_exception' if added to choices
                search_task.status = 'failed' 
                search_task.error_message = f"Task Execution Error: {str(e)[:500]}"
                search_task.save(update_fields=['status', 'error_message', 'updated_at'])
        # Decide whether to retry based on the exception type and retry count
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)): # Example: retry network issues
            logger.warning(f"Network-related error for STID {search_task_id}. Retrying if attempts left ({self.request.retries}/{self.max_retries}).")
            raise self.retry(exc=e, countdown=int(default_retry_delay * (2 ** self.request.retries))) # Exponential backoff
        else: # For other unexpected errors, don't retry, or retry only once.
             logger.error(f"Non-network unhandled error for STID {search_task_id}. Final attempt or no retry. Error: {e}")
             # If you don't raise self.retry, Celery marks it as failed after this run.
             # Depending on the error, one final retry might be acceptable.
             if self.request.retries < self.max_retries:
                 raise self.retry(exc=e)
             # If retries exhausted, it will be marked as failed by Celery. The DB update above should reflect this.
        return {"status": "failed_exception", "search_task_id": str(search_task_id), "message": "Unhandled exception during task execution."}


@shared_task(bind=True, name='api.process_video_edit_task', max_retries=1, default_retry_delay=120, queue='video_editing')
def process_video_edit_task(self, edit_task_id):
    logger.info(f"[Celery TASK START - Q:video_editing] process_video_edit_task for EditTask ID: {edit_task_id}. Celery Task ID: {self.request.id}")
    edit_task = None
    try:
        with transaction.atomic():
            edit_task = EditTask.objects.select_for_update().get(id=edit_task_id)
            if edit_task.status not in ['pending', 'queued', 'failed_timeout']: # Allow retry on specific fail states if needed
                logger.warning(f"EditTask ETID {edit_task_id} already in status '{edit_task.status}'. Skipping.")
                return {"status": edit_task.status, "message": "Task already processed or in an unretryable state."}

            edit_task.status = 'processing' # General processing
            edit_task.celery_task_id = self.request.id
            edit_task.error_message = None # Clear previous errors
            edit_task.save(update_fields=['status', 'celery_task_id', 'error_message', 'updated_at'])
        logger.debug(f"EditTask ETID {edit_task_id} status updated to 'processing'.")

        video_editor_agent = AIVideoEditorAgent()
        project = edit_task.project # Already select_related in previous version of this task

        # Update status to 'downloading_video' before actual download attempt
        with transaction.atomic():
            edit_task.status = 'downloading_video'
            edit_task.save(update_fields=['status', 'updated_at'])

        input_video_path_or_url = None
        if project.original_video_source and project.original_video_source.original_url:
            input_video_path_or_url = project.original_video_source.original_url
        elif project.uploaded_video_path:
            if not project.uploaded_video_path.startswith(('http://', 'https://')):
                input_video_path_or_url = os.path.join(settings.MEDIA_ROOT, project.uploaded_video_path)
            else:
                input_video_path_or_url = project.uploaded_video_path
        else:
            raise TaskOperationalError("No video source specified for editing in the project.") # Non-retryable

        # Status updates for different stages of editing by AIVideoEditorAgent are expected
        # to be handled within perform_edit or called from there.
        # Here, we set 'interpreting_prompt' before calling.
        with transaction.atomic():
            edit_task.status = 'interpreting_prompt'
            edit_task.save(update_fields=['status', 'updated_at'])
        
        logger.debug(f"Calling AIVideoEditorAgent.perform_edit for ETID {edit_task_id} with prompt: '{edit_task.prompt_text[:100]}...'")
        edit_result = video_editor_agent.perform_edit(
            video_path_or_url=input_video_path_or_url,
            prompt=edit_task.prompt_text,
            edit_task_id_for_agent=str(edit_task.id) # Agent can use this to update EditTask status further
        )
        logger.debug(f"AIVideoEditorAgent returned for EditTask {edit_task_id}: {edit_result}")

        with transaction.atomic():
            edit_task = EditTask.objects.select_for_update().get(id=edit_task_id) # Re-fetch
            # Agent might have updated status directly, or we use its result here.
            # Prefer agent updating status for granularity. If not, use result here.
            if edit_result.get('status') == 'completed':
                edit_task.status = 'completed'
                edit_task.result_media_path = edit_result.get('output_media_path')
                edit_task.error_message = None
            else: # Agent determined failure
                edit_task.status = edit_result.get('final_task_status', 'failed') # Agent can specify granular fail status
                edit_task.error_message = edit_result.get('error', 'Unknown video editing error')[:1000]
            edit_task.updated_at = timezone.now()
            edit_task.save()
        
        logger.info(f"[Celery TASK END - Q:video_editing] process_video_edit_task for ETID: {edit_task_id}. Final Status: {edit_task.status}")
        return {"status": edit_task.status, "edit_task_id": str(edit_task_id), "message": "Video edit processing finished."}

    except EditTask.DoesNotExist:
        logger.error(f"EditTask ETID {edit_task_id} not found. No retry.")
        return {"status": "error_task_not_found", "edit_task_id": str(edit_task_id), "message": "EditTask not found."}
    except TaskOperationalError as toe:
        logger.error(f"TaskOperationalError in process_video_edit_task for ETID {edit_task_id}: {toe}", exc_info=True)
        if edit_task:
            with transaction.atomic():
                edit_task = EditTask.objects.select_for_update().get(id=edit_task_id)
                # Use a specific operational failure status if defined in EditTask.STATUS_CHOICES
                edit_task.status = 'failed' # Or a more specific 'failed_configuration' or 'failed_input'
                edit_task.error_message = f"Operational Error: {str(toe)[:500]}"
                edit_task.save(update_fields=['status', 'error_message', 'updated_at'])
        return {"status": "failed_operational", "edit_task_id": str(edit_task_id), "message": str(toe)}
    except Exception as e:
        logger.error(f"Unhandled exception in process_video_edit_task for ETID {edit_task_id}: {e}", exc_info=True)
        if edit_task:
            with transaction.atomic():
                edit_task = EditTask.objects.select_for_update().get(id=edit_task_id)
                # Use a generic 'failed' or a more specific 'failed_uncaught_exception'
                edit_task.status = 'failed' 
                edit_task.error_message = f"Task Execution Error: {str(e)[:500]}"
                edit_task.save(update_fields=['status', 'error_message', 'updated_at'])
        
        if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, yt_dlp.utils.DownloadError)):
            logger.warning(f"Download/Network error for ETID {edit_task_id}. Retrying if attempts left.")
            edit_task.status = 'failed_download' # Set specific failure for UI
            edit_task.save(update_fields=['status', 'error_message', 'updated_at'])
            raise self.retry(exc=e, countdown=int(default_retry_delay * (2 ** self.request.retries)))
        else:
            logger.error(f"Non-network unhandled error for ETID {edit_task_id}. Final attempt or no retry.")
            if self.request.retries < self.max_retries:
                raise self.retry(exc=e)
        return {"status": "failed_exception", "edit_task_id": str(edit_task_id), "message": "Unhandled exception during video edit task."}
