# backend/api/tasks.py
import logging
import os
from django.utils import timezone
from django.conf import settings
from celery import shared_task, Celery # Use shared_task for tasks within Django apps

# Import models (ensure this doesn't create circular dependencies at module load time)
# It's often safer to import models inside the task function if issues arise,
# but for clarity, we'll import at the top here.
from .models import SearchTask, EditTask, VideoSource, Video

# Import AI Agent Orchestrators/Agents
# Ensure these are importable and well-encapsulated
from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator
from backend.ai_agents.ai_video_editor_agent import AIVideoEditorAgent

logger = logging.getLogger(__name__) # Standard Python logger

# To get the Celery app instance if needed (though shared_task usually handles this)
# from papri_project.celery import app as celery_app


@shared_task(bind=True, name='api.process_search_query_task', max_retries=2, default_retry_delay=60) # Retry twice with 1 min delay
def process_search_query_task(self, search_task_id):
    """
    Celery task to orchestrate the entire search process for a given SearchTask.
    """
    logger.info(f"[Celery TASK START] process_search_query_task for STID: {search_task_id}. Celery Task ID: {self.request.id}")
    
    try:
        search_task = SearchTask.objects.get(id=search_task_id)
        search_task.status = 'processing'
        search_task.celery_task_id = self.request.id # Store Celery's internal task ID
        search_task.save(update_fields=['status', 'celery_task_id'])
        logger.debug(f"SearchTask {search_task_id} status updated to 'processing'.")

        # Construct search parameters for the orchestrator
        # If query_image_ref is a relative path from MEDIA_ROOT, make it absolute for the agent
        full_image_path = None
        if search_task.query_image_ref:
            if not search_task.query_image_ref.startswith(('http://', 'https://')): # Assuming it's a path relative to MEDIA_ROOT
                 full_image_path = os.path.join(settings.MEDIA_ROOT, search_task.query_image_ref)
            else: # It's already a full URL or an absolute path that the agent can handle
                full_image_path = search_task.query_image_ref

        search_parameters = {
            'query_text': search_task.query_text,
            'query_image_path': full_image_path, # Orchestrator expects a full path or resolvable ref
            'query_video_url': search_task.query_video_url,
            'applied_filters': search_task.applied_filters_json or {},
            'user_id': str(search_task.user_id) if search_task.user else None,
            'session_id': search_task.session_id,
            'search_task_model_id': str(search_task.id) # Pass the DB ID for logging/tracing within agents
        }
        
        logger.debug(f"Initializing PapriAIAgentOrchestrator for STID: {search_task_id} with params: {search_parameters}")
        orchestrator = PapriAIAgentOrchestrator(papri_search_task_id=search_task_id)
        
        # The orchestrator's execute_search method should handle all sub-agent calls
        # and return a dictionary with results or an error.
        results_data = orchestrator.execute_search(search_parameters)
        logger.debug(f"Orchestrator finished for STID: {search_task_id}. Raw results_data: {str(results_data)[:500]}...") # Log snippet of result

        if "error" in results_data:
            logger.error(f"Orchestration failed for STID {search_task_id}: {results_data['error']}")
            search_task.status = 'failed'
            search_task.error_message = str(results_data["error"])[:1000] # Truncate error message
        else:
            # Successfully completed or partially completed
            search_task.status = results_data.get("search_status_overall", 'completed') # Orchestrator can specify 'partial_results'
            
            # Store ranked canonical video IDs and detailed structured results
            search_task.result_video_ids_json = results_data.get("persisted_video_ids_ranked", [])
            search_task.detailed_results_info_json = results_data.get("results_data_detailed", [])
            
            search_task.error_message = None # Clear any previous error
            logger.info(f"Search task STID {search_task_id} processed. Status: {search_task.status}. Results count: {len(search_task.result_video_ids_json)}")
        
        search_task.updated_at = timezone.now()
        search_task.save()
        
        logger.info(f"[Celery TASK END] process_search_query_task for STID: {search_task_id}. Final Status: {search_task.status}")
        return {"status": search_task.status, "search_task_id": str(search_task_id), "message": "Search processing finished."}

    except SearchTask.DoesNotExist:
        logger.error(f"SearchTask with ID {search_task_id} not found in Celery task.")
        # Cannot update task status if it doesn't exist, so no retry.
        return {"status": "error", "search_task_id": str(search_task_id), "message": "SearchTask not found."}
    except Exception as e:
        logger.error(f"Unhandled exception in process_search_query_task for STID {search_task_id}: {e}", exc_info=True)
        try:
            # Attempt to mark task as failed in DB if an unexpected error occurs
            task_to_fail = SearchTask.objects.get(id=search_task_id) # Re-fetch to avoid stale object
            task_to_fail.status = 'failed'
            task_to_fail.error_message = f"Celery Task Execution Error: {str(e)[:500]}" # Truncate
            task_to_fail.save()
        except SearchTask.DoesNotExist:
            logger.error(f"Failed to update SearchTask {search_task_id} to 'failed' status as it was not found on error handling.")
        except Exception as db_err: # noqa
            logger.error(f"Could not update SearchTask {search_task_id} to 'failed' status after unhandled Celery error: {db_err}", exc_info=True)
        
        # Retry the task if max_retries not exceeded
        # The `raise self.retry(...)` call will trigger Celery's retry mechanism.
        # If retries are exhausted, Celery marks it as failed.
        raise self.retry(exc=e)


@shared_task(bind=True, name='api.process_video_edit_task', max_retries=1, default_retry_delay=120) # Retry once after 2 mins
def process_video_edit_task(self, edit_task_id):
    """
    Celery task to handle AI-powered video editing.
    """
    logger.info(f"[Celery TASK START] process_video_edit_task for EditTask ID: {edit_task_id}. Celery Task ID: {self.request.id}")
    
    try:
        edit_task = EditTask.objects.select_related('project__original_video_source__video', 'project__user').get(id=edit_task_id)
        edit_task.status = 'processing'
        edit_task.celery_task_id = self.request.id
        edit_task.save(update_fields=['status', 'celery_task_id'])
        logger.debug(f"EditTask {edit_task_id} status updated to 'processing'.")

        video_editor_agent = AIVideoEditorAgent() # Initialize the agent

        # Determine video input for the agent
        input_video_path_or_url = None
        project = edit_task.project

        if project.original_video_source and project.original_video_source.original_url:
            # Video is from Papri's search results, use its original URL
            # The agent will need to be capable of downloading/streaming from this URL
            input_video_path_or_url = project.original_video_source.original_url
            logger.info(f"Edit task {edit_task_id} will use video from source: {input_video_path_or_url}")
        elif project.uploaded_video_name:
            # Video was uploaded by the user, construct full path from MEDIA_ROOT
            # uploaded_video_name should be a path relative to MEDIA_ROOT
            if not project.uploaded_video_name.startswith(('http://', 'https://')):
                input_video_path_or_url = os.path.join(settings.MEDIA_ROOT, project.uploaded_video_name)
            else: # It's already a full URL, should not happen for uploaded_video_name
                input_video_path_or_url = project.uploaded_video_name
            logger.info(f"Edit task {edit_task_id} will use user-uploaded video: {input_video_path_or_url}")
        else:
            logger.error(f"No video source (VideoSource URL or uploaded file path) specified for EditTask {edit_task_id}.")
            raise ValueError("No video source specified for editing in the project.")

        # Call the agent's method to perform the edit
        # The agent method should return a dict like:
        # {'status': 'completed', 'output_media_path': 'edited_videos/user_X/output.mp4', 'output_preview_url': '...'}
        # or {'status': 'failed', 'error': 'Details of failure'}
        # 'output_media_path' is relative to MEDIA_ROOT or a full URL if stored externally.
        
        logger.debug(f"Calling AIVideoEditorAgent.perform_edit for EditTask {edit_task_id} with prompt: '{edit_task.prompt_text[:100]}...'")
        edit_result = video_editor_agent.perform_edit(
            video_path_or_url=input_video_path_or_url,
            prompt=edit_task.prompt_text,
            edit_task_id_for_agent=str(edit_task.id) # Pass ID for agent to name output files etc.
        )
        logger.debug(f"AIVideoEditorAgent returned for EditTask {edit_task_id}: {edit_result}")

        if edit_result.get('status') == 'completed':
            edit_task.status = 'completed'
            edit_task.result_media_path = edit_result.get('output_media_path') # Agent provides path relative to MEDIA_ROOT or full URL
            edit_task.result_preview_url = edit_result.get('output_preview_url') # Optional preview URL
            edit_task.error_message = None
            logger.info(f"EditTask {edit_task_id} completed successfully. Output path: {edit_task.result_media_path}")
        else:
            edit_task.status = 'failed'
            edit_task.error_message = edit_result.get('error', 'Unknown video editing error')[:1000] # Truncate
            logger.error(f"EditTask {edit_task_id} failed. Error: {edit_task.error_message}")
        
        edit_task.updated_at = timezone.now()
        edit_task.save()
        
        logger.info(f"[Celery TASK END] process_video_edit_task for EditTask ID: {edit_task_id}. Final Status: {edit_task.status}")
        return {"status": edit_task.status, "edit_task_id": str(edit_task_id), "message": "Video edit processing finished."}

    except EditTask.DoesNotExist:
        logger.error(f"EditTask with ID {edit_task_id} not found in Celery task.")
        return {"status": "error", "edit_task_id": str(edit_task_id), "message": "EditTask not found."}
    except ValueError as ve: # Specific error like no video source
        logger.error(f"ValueError in process_video_edit_task for ETID {edit_task_id}: {ve}", exc_info=True)
        try:
            task_to_fail = EditTask.objects.get(id=edit_task_id)
            task_to_fail.status = 'failed'
            task_to_fail.error_message = f"Configuration Error: {str(ve)[:500]}"
            task_to_fail.save()
        except Exception: pass # Ignore errors during error logging for this specific case
        return {"status": "failed", "edit_task_id": str(edit_task_id), "message": str(ve)}
    except Exception as e:
        logger.error(f"Unhandled exception in process_video_edit_task for ETID {edit_task_id}: {e}", exc_info=True)
        try:
            task_to_fail = EditTask.objects.get(id=edit_task_id)
            task_to_fail.status = 'failed'
            task_to_fail.error_message = f"Celery Task Execution Error: {str(e)[:500]}"
            task_to_fail.save()
        except EditTask.DoesNotExist:
            logger.error(f"Failed to update EditTask {edit_task_id} to 'failed' status as it was not found on error handling.")
        except Exception as db_err: # noqa
            logger.error(f"Could not update EditTask {edit_task_id} to 'failed' status after unhandled Celery error: {db_err}", exc_info=True)
        raise self.retry(exc=e)

# Example of a periodic task (if you need one, e.g., cleanup old SearchTasks)
# from celery.schedules import crontab
# @shared_task(name='api.cleanup_old_search_tasks_periodic')
# def cleanup_old_search_tasks_periodic():
#     one_week_ago = timezone.now() - timezone.timedelta(days=7)
#     # Delete tasks older than one week that are completed or failed and have no user
#     # Be careful with delete operations!
#     # deleted_count, _ = SearchTask.objects.filter(
#     #     user__isnull=True,
#     #     status__in=['completed', 'failed'],
#     #     created_at__lt=one_week_ago
#     # ).delete()
#     # logger.info(f"Periodic Cleanup: Deleted {deleted_count} old anonymous search tasks.")
#     pass

# If using django-celery-beat, you would schedule this in Django Admin.
# Example schedule in settings.py if not using DB scheduler for beat:
# CELERY_BEAT_SCHEDULE = {
#     'cleanup-old-searches-every-day': {
#         'task': 'api.cleanup_old_search_tasks_periodic',
#         'schedule': crontab(hour=3, minute=0), # Runs daily at 3 AM
#     },
# }
