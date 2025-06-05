# backend/api/tasks.py
import logging
import os
from django.utils import timezone
from django.conf import settings
from celery import shared_task # Use shared_task for tasks within Django apps

# Import models
from .models import SearchTask, EditTask # VideoSource, Video (if directly used in tasks)

# Import AI Agent Orchestrators/Agents
from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator
from backend.ai_agents.ai_video_editor_agent import AIVideoEditorAgent

logger = logging.getLogger(__name__)

@shared_task(bind=True, name='api.process_search_query_task', max_retries=2, default_retry_delay=60, queue='ai_processing')
def process_search_query_task(self, search_task_id):
    """
    Celery task to orchestrate the entire search process for a given SearchTask.
    Routed to 'ai_processing' queue.
    """
    logger.info(f"[Celery TASK START - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Celery Task ID: {self.request.id}")
    
    try:
        search_task = SearchTask.objects.get(id=search_task_id)
        search_task.status = 'processing'
        search_task.celery_task_id = self.request.id
        search_task.save(update_fields=['status', 'celery_task_id'])
        logger.debug(f"SearchTask {search_task_id} status updated to 'processing'.")

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
        
        logger.debug(f"Initializing PapriAIAgentOrchestrator for STID: {search_task_id} with params: {search_parameters}")
        orchestrator = PapriAIAgentOrchestrator(papri_search_task_id=search_task_id)
        
        results_data = orchestrator.execute_search(search_parameters)
        logger.debug(f"Orchestrator finished for STID: {search_task_id}. Raw results_data: {str(results_data)[:500]}...")

        if "error" in results_data:
            logger.error(f"Orchestration failed for STID {search_task_id}: {results_data['error']}")
            search_task.status = 'failed'
            search_task.error_message = str(results_data["error"])[:1000]
        else:
            search_task.status = results_data.get("search_status_overall", 'completed')
            search_task.result_video_ids_json = results_data.get("persisted_video_ids_ranked", [])
            search_task.detailed_results_info_json = results_data.get("results_data_detailed", [])
            search_task.error_message = None
            logger.info(f"Search task STID {search_task_id} processed. Status: {search_task.status}. Results count: {len(search_task.result_video_ids_json)}")
        
        search_task.updated_at = timezone.now()
        search_task.save()
        
        logger.info(f"[Celery TASK END - Q:ai_processing] process_search_query_task for STID: {search_task_id}. Final Status: {search_task.status}")
        return {"status": search_task.status, "search_task_id": str(search_task_id), "message": "Search processing finished."}

    except SearchTask.DoesNotExist:
        logger.error(f"SearchTask with ID {search_task_id} not found in Celery task.")
        return {"status": "error", "search_task_id": str(search_task_id), "message": "SearchTask not found."}
    except Exception as e:
        logger.error(f"Unhandled exception in process_search_query_task for STID {search_task_id}: {e}", exc_info=True)
        try:
            task_to_fail = SearchTask.objects.get(id=search_task_id)
            task_to_fail.status = 'failed'
            task_to_fail.error_message = f"Celery Task Execution Error: {str(e)[:500]}"
            task_to_fail.save()
        except SearchTask.DoesNotExist:
            logger.error(f"Failed to update SearchTask {search_task_id} to 'failed' status as it was not found on error handling.")
        except Exception as db_err: # noqa
            logger.error(f"Could not update SearchTask {search_task_id} to 'failed' status after unhandled Celery error: {db_err}", exc_info=True)
        raise self.retry(exc=e)


@shared_task(bind=True, name='api.process_video_edit_task', max_retries=1, default_retry_delay=120, queue='video_editing')
def process_video_edit_task(self, edit_task_id):
    """
    Celery task to handle AI-powered video editing.
    Routed to 'video_editing' queue.
    """
    logger.info(f"[Celery TASK START - Q:video_editing] process_video_edit_task for EditTask ID: {edit_task_id}. Celery Task ID: {self.request.id}")
    
    try:
        # edit_task = EditTask.objects.select_related('project__original_video_source__video', 'project__user').get(id=edit_task_id)
        # Corrected select_related based on your actual models
        edit_task = EditTask.objects.select_related('project__original_video_source', 'project__user').get(id=edit_task_id)

        edit_task.status = 'processing'
        edit_task.celery_task_id = self.request.id
        edit_task.save(update_fields=['status', 'celery_task_id'])
        logger.debug(f"EditTask {edit_task_id} status updated to 'processing'.")

        video_editor_agent = AIVideoEditorAgent()

        input_video_path_or_url = None
        project = edit_task.project

        if project.original_video_source and project.original_video_source.original_url:
            input_video_path_or_url = project.original_video_source.original_url
            logger.info(f"Edit task {edit_task_id} will use video from source: {input_video_path_or_url}")
        # Corrected attribute name from 'uploaded_video_name' to 'uploaded_video_path' based on probable model def
        elif project.uploaded_video_path: 
            if not project.uploaded_video_path.startswith(('http://', 'https://')):
                input_video_path_or_url = os.path.join(settings.MEDIA_ROOT, project.uploaded_video_path)
            else:
                input_video_path_or_url = project.uploaded_video_path
            logger.info(f"Edit task {edit_task_id} will use user-uploaded video: {input_video_path_or_url}")
        else:
            logger.error(f"No video source (VideoSource URL or uploaded file path) specified for EditTask {edit_task_id}.")
            raise ValueError("No video source specified for editing in the project.")
        
        logger.debug(f"Calling AIVideoEditorAgent.perform_edit for EditTask {edit_task_id} with prompt: '{edit_task.prompt_text[:100]}...'")
        edit_result = video_editor_agent.perform_edit(
            video_path_or_url=input_video_path_or_url,
            prompt=edit_task.prompt_text,
            edit_task_id_for_agent=str(edit_task.id)
        )
        logger.debug(f"AIVideoEditorAgent returned for EditTask {edit_task_id}: {edit_result}")

        if edit_result.get('status') == 'completed':
            edit_task.status = 'completed'
            edit_task.result_media_path = edit_result.get('output_media_path')
            # edit_task.result_preview_url = edit_result.get('output_preview_url') # This field was removed from EditTask model
            edit_task.error_message = None
            logger.info(f"EditTask {edit_task_id} completed successfully. Output path: {edit_task.result_media_path}")
        else:
            edit_task.status = 'failed'
            edit_task.error_message = edit_result.get('error', 'Unknown video editing error')[:1000]
            logger.error(f"EditTask {edit_task_id} failed. Error: {edit_task.error_message}")
        
        edit_task.updated_at = timezone.now()
        edit_task.save()
        
        logger.info(f"[Celery TASK END - Q:video_editing] process_video_edit_task for EditTask ID: {edit_task_id}. Final Status: {edit_task.status}")
        return {"status": edit_task.status, "edit_task_id": str(edit_task_id), "message": "Video edit processing finished."}

    except EditTask.DoesNotExist:
        logger.error(f"EditTask with ID {edit_task_id} not found in Celery task.")
        return {"status": "error", "edit_task_id": str(edit_task_id), "message": "EditTask not found."}
    except ValueError as ve:
        logger.error(f"ValueError in process_video_edit_task for ETID {edit_task_id}: {ve}", exc_info=True)
        try:
            task_to_fail = EditTask.objects.get(id=edit_task_id)
            task_to_fail.status = 'failed'
            task_to_fail.error_message = f"Configuration Error: {str(ve)[:500]}"
            task_to_fail.save()
        except Exception: pass
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

# Example periodic task (commented out from your original)
# from celery.schedules import crontab
# @shared_task(name='api.cleanup_old_search_tasks_periodic', queue='default') # Assign to default queue
# def cleanup_old_search_tasks_periodic():
#     # ... (implementation)
#     pass
