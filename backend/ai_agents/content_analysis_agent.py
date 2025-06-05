# backend/ai_agents/content_analysis_agent.py
import logging
import os
import tempfile
import shutil # For rmtree
import yt_dlp 

from django.conf import settings
from django.utils import timezone as django_timezone # Use a distinct alias for Django's timezone

# Import Django models (used for type hinting and updating status)
from api.models import VideoSource 

# Import the global analyzer instances getter functions
from api.analyzer_instances import get_visual_analyzer, get_transcript_analyzer

logger = logging.getLogger(__name__)

class ContentAnalysisAgent:
    def __init__(self):
        # Use the globally initialized instances provided by getter functions
        # These functions return the instance or None if initialization failed.
        self.transcript_analyzer = get_transcript_analyzer()
        self.visual_analyzer = get_visual_analyzer()
        
        if not self.transcript_analyzer:
            logger.critical("ContentAnalysisAgent: TranscriptAnalyzer global instance is NOT available. Transcript analysis will be severely limited or fail.")
        if not self.visual_analyzer:
            logger.critical("ContentAnalysisAgent: VisualAnalyzer global instance is NOT available. Visual analysis will be severely limited or fail.")
            
        logger.info("ContentAnalysisAgent initialized. Attempting to use global/shared sub-analyzers.")

    def _download_video_if_needed(self, video_url: str, video_source_id: any) -> Optional[str]:
        """
        Downloads a video from a URL to a temporary local file for analysis.
        Returns the path to the downloaded file or None if download fails.
        The caller is responsible for cleaning up the parent directory of the returned file path.
        """
        if not video_url:
            logger.warning(f"VSID {video_source_id}: Download skipped, no video URL provided.")
            return None
        
        # Create a unique temporary directory for this download to manage cleanup easily
        # The temp_dir itself will be the parent of the actual video file.
        parent_temp_dir = tempfile.mkdtemp(prefix=f"papri_dl_vsid_{video_source_id}_")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best',
            'outtmpl': os.path.join(parent_temp_dir, '%(id)s.%(ext)s'), # File will be inside parent_temp_dir
            'quiet': True,
            'logger': logging.getLogger(f"{__name__}.yt_dlp_video_dl"), # Sub-logger for yt-dlp
            'noplaylist': True,
            'noprogress': True,
            'max_filesize': settings.MAX_DOWNLOAD_FILE_SIZE_MB * 1024 * 1024 if hasattr(settings, 'MAX_DOWNLOAD_FILE_SIZE_MB') else None, # e.g. 200MB
            'socket_timeout': 60, # Timeout for network operations
        }
        
        logger.info(f"VSID {video_source_id}: Attempting to download video from URL: {video_url} into dir: {parent_temp_dir}")
        downloaded_file_path = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True) # Download the video
                
                # Try to get the exact path of the downloaded file
                if info_dict and info_dict.get('_filename'): # yt-dlp version >= 2023.06.22
                    downloaded_file_path = info_dict['_filename']
                elif info_dict: # Older way, construct from template if possible
                    downloaded_file_path = ydl.prepare_filename(info_dict)
                
                # Verify file exists and is not empty
                if downloaded_file_path and os.path.exists(downloaded_file_path) and os.path.getsize(downloaded_file_path) > 1024: # Check for >1KB
                    logger.info(f"VSID {video_source_id}: Video downloaded successfully to: {downloaded_file_path}")
                    # Return the path to the file, not the directory, but caller knows parent for cleanup.
                    return downloaded_file_path 
                else:
                    # If exact path not found, try to find any media file in the directory (less reliable)
                    found_files = [f for f in os.listdir(parent_temp_dir) if os.path.isfile(os.path.join(parent_temp_dir, f)) and f.split('.')[-1] in ['mp4','mkv','webm','mov','avi']]
                    if found_files:
                        downloaded_file_path = os.path.join(parent_temp_dir, found_files[0])
                        logger.info(f"VSID {video_source_id}: Video downloaded (found by scan): {downloaded_file_path}")
                        return downloaded_file_path
                    
                    error_msg = "yt-dlp reported success but downloaded file issue (not found, empty, or unexpected name)."
                    logger.error(f"VSID {video_source_id}: {error_msg} Dir: {parent_temp_dir}. YDL Info: {str(info_dict)[:500]}")
                    # No specific error message to save on VideoSource model from here, rely on caller.

        except yt_dlp.utils.DownloadError as dl_err:
            logger.error(f"VSID {video_source_id}: yt-dlp DownloadError for URL {video_url}: {dl_err}")
        except Exception as e:
            logger.error(f"VSID {video_source_id}: Generic error downloading video {video_url}: {e}", exc_info=True)
        
        # If download failed or file not verified, cleanup the created parent directory
        if parent_temp_dir and os.path.exists(parent_temp_dir):
            try:
                shutil.rmtree(parent_temp_dir)
                logger.info(f"VSID {video_source_id}: Cleaned up temporary download directory {parent_temp_dir} due to download failure or issue.")
            except Exception as cleanup_err:
                logger.error(f"VSID {video_source_id}: Error cleaning up temp download directory {parent_temp_dir}: {cleanup_err}")
            
        return None # Explicitly return None on any failure


    def analyze_video_content(self, video_source_model: VideoSource, raw_video_item_data: dict) -> dict:
        """
        Orchestrates content analysis (transcript and visual) for a given VideoSource.
        Updates the `video_source_model` status based on analysis outcomes.
        """
        # Ensure type for video_source_model for clarity, though it's passed by MainOrchestrator
        if not isinstance(video_source_model, VideoSource):
            logger.error("ContentAnalysisAgent: Received invalid video_source_model type.")
            return {"errors": ["Invalid video_source_model provided."]}

        logger.info(f"ContentAnalysisAgent: Starting analysis for VSID {video_source_model.id}, Title: {video_source_model.video.title[:50] if video_source_model.video else 'N/A'}")
        
        overall_analysis_report = {
            "video_source_id": video_source_model.id,
            "transcript_analysis": {"status": "not_attempted", "errors": []}, # Initialize sub-reports
            "visual_analysis": {"status": "not_attempted", "errors": []},
            "analysis_completed_at": None,
            "final_status_set": None, # To track what overall status was determined
            "errors": [] # Top-level errors for CAAgent itself
        }
        
        has_critical_errors = False # Flag for overall failure of CA stage

        # --- 1. Transcript Analysis ---
        if self.transcript_analyzer:
            if raw_video_item_data.get('transcript_text') or raw_video_item_data.get('transcript_vtt_url'):
                logger.debug(f"VSID {video_source_model.id}: Initiating transcript analysis.")
                video_source_model.processing_status = 'transcript_processing'
                video_source_model.processing_error_message = None # Clear previous errors for this stage
                video_source_model.save(update_fields=['processing_status', 'processing_error_message', 'updated_at'])
                try:
                    transcript_results = self.transcript_analyzer.process_transcript_for_video_source(
                        video_source_model, # Passes the Django model instance
                        raw_video_item_data  # Passes the dict from SOIAgent
                    )
                    overall_analysis_report["transcript_analysis"] = transcript_results
                    if transcript_results.get("errors") or "failed" in transcript_results.get("status", ""):
                        # Log errors from transcript_results to video_source_model.processing_error_message
                        err_join = '; '.join(transcript_results.get("errors", ["Transcript processing failed."])[:2])
                        video_source_model.processing_error_message = f"Transcript Stage: {err_join}"
                        logger.warning(f"VSID {video_source_model.id}: Transcript analysis reported errors: {err_join}")
                    video_source_model.processing_status = 'transcript_processed' # Will be updated by TA, but set an intermediate
                except Exception as e:
                    logger.error(f"VSID {video_source_model.id}: Critical error during transcript_analyzer call: {e}", exc_info=True)
                    has_critical_errors = True
                    err_msg = f"Transcript analysis system error: {str(e)[:150]}"
                    overall_analysis_report["transcript_analysis"]["errors"].append(err_msg)
                    overall_analysis_report["transcript_analysis"]["status"] = "system_error"
                    video_source_model.processing_error_message = err_msg
                    video_source_model.processing_status = 'processing_failed'
            else:
                logger.info(f"VSID {video_source_model.id}: No transcript data (text or VTT URL) in raw_video_item_data. Skipping transcript analysis.")
                overall_analysis_report["transcript_analysis"] = {"status": "skipped_no_data", "message": "No transcript data provided."}
                # If no transcript, processing_status might remain 'metadata_fetched' or similar
                if video_source_model.processing_status == 'pending' or video_source_model.processing_status == 'metadata_fetched':
                    # It's not an error, but it's not transcript_processed either
                    pass # Let visual analysis proceed if possible.
        else:
            logger.warning(f"VSID {video_source_model.id}: TranscriptAnalyzer not available. Skipping transcript analysis.")
            overall_analysis_report["transcript_analysis"] = {"status": "skipped_analyzer_unavailable", "message": "TranscriptAnalyzer service not available."}
            # This is a system configuration issue, might mark as error or requires review.
            video_source_model.processing_error_message = (video_source_model.processing_error_message or "") + "Transcript analyzer missing. "
            has_critical_errors = True


        # --- 2. Visual Analysis ---
        local_video_file_path_for_visuals = raw_video_item_data.get('local_file_path') # If SOIAgent pre-downloaded
        temp_download_dir_to_cleanup_after_visuals = None # Path to the PARENT directory of the downloaded file

        if self.visual_analyzer:
            if not local_video_file_path_for_visuals and video_source_model.original_url:
                logger.info(f"VSID {video_source_model.id}: No pre-downloaded local file for visual analysis. Attempting download from {video_source_model.original_url}")
                video_source_model.meta_visual_processing_status = 'visual_downloading'
                video_source_model.meta_visual_processing_error = None # Clear previous errors
                video_source_model.save(update_fields=['meta_visual_processing_status', 'meta_visual_processing_error', 'updated_at'])
                
                # _download_video_if_needed returns path to file, or None
                local_video_file_path_for_visuals = self._download_video_if_needed(video_source_model.original_url, video_source_model.id)
                if local_video_file_path_for_visuals:
                    temp_download_dir_to_cleanup_after_visuals = os.path.dirname(local_video_file_path_for_visuals)
            
            if local_video_file_path_for_visuals and os.path.exists(local_video_file_path_for_visuals):
                video_source_model.meta_visual_processing_status = 'visual_processing'
                video_source_model.save(update_fields=['meta_visual_processing_status', 'updated_at'])
                logger.debug(f"VSID {video_source_model.id}: Starting visual analysis from path: {local_video_file_path_for_visuals}")
                try:
                    visual_results = self.visual_analyzer.process_video_frames(
                        video_source_model, # Django model instance
                        local_video_file_path_for_visuals,
                        frame_interval_sec=getattr(settings, 'VISUAL_FRAME_INTERVAL_SEC', 2) # Configurable
                    )
                    overall_analysis_report["visual_analysis"] = visual_results
                    if visual_results.get("errors") or "failed" in visual_results.get("status", ""): # Check for specific status if VA returns it
                        err_join = '; '.join(visual_results.get("errors", ["Visual processing failed."])[:2])
                        video_source_model.meta_visual_processing_error = f"Visual Stage: {err_join}"
                        logger.warning(f"VSID {video_source_model.id}: Visual analysis reported errors: {err_join}")
                    video_source_model.meta_visual_processing_status = 'visual_processed'
                    video_source_model.last_visual_indexed_at = django_timezone.now()
                except Exception as e:
                    logger.error(f"VSID {video_source_model.id}: Critical error during visual_analyzer call: {e}", exc_info=True)
                    has_critical_errors = True
                    err_msg = f"Visual analysis system error: {str(e)[:150]}"
                    overall_analysis_report["visual_analysis"]["errors"].append(err_msg)
                    overall_analysis_report["visual_analysis"]["status"] = "system_error"
                    video_source_model.meta_visual_processing_error = err_msg
                    video_source_model.meta_visual_processing_status = 'processing_failed'
                finally:
                    # Clean up the PARENT directory of the downloaded video file if it was created by this agent
                    if temp_download_dir_to_cleanup_after_visuals and os.path.exists(temp_download_dir_to_cleanup_after_visuals):
                        try:
                            shutil.rmtree(temp_download_dir_to_cleanup_after_visuals)
                            logger.info(f"VSID {video_source_model.id}: Cleaned up temporary download directory used for visual analysis: {temp_download_dir_to_cleanup_after_visuals}")
                        except Exception as e_clean:
                            logger.error(f"VSID {video_source_model.id}: Error cleaning up temp dir {temp_download_dir_to_cleanup_after_visuals} after visual analysis: {e_clean}", exc_info=True)
            else: # No local video file path available or download failed.
                logger.info(f"VSID {video_source_model.id}: No local video file available for visual analysis. Skipping.")
                overall_analysis_report["visual_analysis"] = {"status": "skipped_no_file", "message": "No local video file for visual analysis."}
                # If download failed, _download_video_if_needed would have logged it.
                # Update status on model if it was 'visual_downloading' and failed.
                if video_source_model.meta_visual_processing_status == 'visual_downloading':
                    video_source_model.meta_visual_processing_status = 'download_failed'
                    video_source_model.meta_visual_processing_error = (video_source_model.meta_visual_processing_error or "") + "Video download failed for visual analysis. "

        else: # Visual Analyzer not available
            logger.warning(f"VSID {video_source_model.id}: VisualAnalyzer not available. Skipping visual analysis.")
            overall_analysis_report["visual_analysis"] = {"status": "skipped_analyzer_unavailable", "message": "VisualAnalyzer service not available."}
            video_source_model.meta_visual_processing_error = (video_source_model.meta_visual_processing_error or "") + "Visual analyzer missing. "
            has_critical_errors = True # If VA is expected but missing, it's a system problem.


        # --- Finalize VideoSource Status ---
        # This logic determines the overall `processing_status` of the VideoSource
        # based on the outcomes of transcript and visual analysis.
        final_processing_status = video_source_model.processing_status # Start with current status from transcript stage
        final_visual_status = video_source_model.meta_visual_processing_status

        if has_critical_errors:
            final_processing_status = 'processing_failed'
            if not video_source_model.processing_error_message: video_source_model.processing_error_message = "Critical system error in CAAgent."
        else:
            # Check transcript status (from Transcript model, potentially updated by TranscriptAnalyzer)
            transcript_processed_successfully = False
            if overall_analysis_report.get("transcript_analysis", {}).get("status") == "processed" or \
               (hasattr(video_source_model, 'transcript_data') and video_source_model.transcript_data and video_source_model.transcript_data.processing_status == 'processed'):
                transcript_processed_successfully = True
            elif overall_analysis_report.get("transcript_analysis", {}).get("status") == "skipped_no_data":
                transcript_processed_successfully = True # Not an error if no data to process

            visual_processed_successfully = False
            if final_visual_status == 'visual_processed' or final_visual_status == 'completed': # 'completed' from older VisualAnalyzer
                visual_processed_successfully = True
            elif final_visual_status in ['pending', 'skipped_no_file', 'not_applicable']: # These are not failure states for visual part alone
                visual_processed_successfully = True # Considered "ok" for overall status if visual part could be skipped

            if transcript_processed_successfully and visual_processed_successfully:
                final_processing_status = 'analysis_complete'
                video_source_model.processing_error_message = None # Clear errors if all successful
                video_source_model.meta_visual_processing_error = None
                video_source_model.last_analyzed_at = django_timezone.now()
                overall_analysis_report["analysis_completed_at"] = video_source_model.last_analyzed_at.isoformat()
            elif 'failed' in final_processing_status or 'failed' in final_visual_status or \
                 'error' in overall_analysis_report.get("transcript_analysis", {}).get("status", "") or \
                 'error' in overall_analysis_report.get("visual_analysis", {}).get("status", ""):
                final_processing_status = 'processing_failed'
                # Error messages should already be set on the model by the failing stage
            else:
                # If one part is processed and other is pending/skipped but not failed, status might be complex.
                # For now, if not 'analysis_complete' and not 'processing_failed', it's likely still in an intermediate state
                # or one part was skipped successfully.
                # Example: transcript_processed, visual_skipped -> could be 'analysis_complete_partial_visual'
                # Defaulting to keep current status if not clearly complete or failed.
                logger.debug(f"VSID {video_source_model.id}: Analysis not fully 'complete' or 'failed'. Current transcript status: {video_source_model.processing_status}, visual: {final_visual_status}")
                if final_processing_status not in ['processing_failed', 'analysis_complete']:
                     # If transcript was processed but visual was only pending/skipped and not critical.
                     if transcript_processed_successfully and final_visual_status in ['pending','skipped_no_file', 'not_applicable', 'visual_downloading']:
                         final_processing_status = 'analysis_complete' # Consider it complete if transcript is done and visual wasn't mandatory or is still pending
                         video_source_model.last_analyzed_at = django_timezone.now() # Mark as analyzed for text part
                         overall_analysis_report["analysis_completed_at"] = video_source_model.last_analyzed_at.isoformat()

        video_source_model.processing_status = final_processing_status
        # visual status is already on video_source_model.meta_visual_processing_status
        
        video_source_model.save(update_fields=[
            'processing_status', 'processing_error_message', 'last_analyzed_at',
            'meta_visual_processing_status', 'meta_visual_processing_error', 'last_visual_indexed_at'
        ])
        
        overall_analysis_report["final_status_set"] = final_processing_status
        logger.info(f"ContentAnalysisAgent: Finished ALL analysis for VSID {video_source_model.id}. Final overall status: {final_processing_status}, Visual status: {video_source_model.meta_visual_processing_status}")
        return overall_analysis_report
