# backend/ai_agents/content_analysis_agent.py
import logging
import os
import tempfile
import yt_dlp # For downloading video if only URL is provided for visual analysis

from django.conf import settings
from django.utils import timezone

# Import sub-analyzers
from .transcript_analyzer import TranscriptAnalyzer
from .visual_analyzer import VisualAnalyzer

# Import Django models (be cautious or import within methods)
from api.models import VideoSource # Used for type hinting and updating status

logger = logging.getLogger(__name__)

class ContentAnalysisAgent:
    def __init__(self):
        self.transcript_analyzer = TranscriptAnalyzer()
        self.visual_analyzer = VisualAnalyzer()
        logger.info("ContentAnalysisAgent initialized with Transcript and Visual Analyzers.")

    def _download_video_if_needed(self, video_url: str, video_source_id: any) -> str | None:
        """Downloads a video from a URL to a temporary local file for analysis."""
        if not video_url: return None
        
        # Create a temporary directory for this download
        temp_dir = tempfile.mkdtemp(prefix=f"papri_dl_vsid_{video_source_id}_")
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best', # Prefer 720p mp4
            'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'), # Save with video ID and extension
            'quiet': True,
            'logger': logging.getLogger(f"{__name__}.yt_dlp_video_dl"),
            'noplaylist': True,
            'noprogress': True,
            # 'max_filesize': '200M', # Optional: limit download size
        }
        
        logger.info(f"Attempting to download video from URL: {video_url} for VSID {video_source_id} to {temp_dir}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True) # Download the video
                # The actual filename is determined by outtmpl and info_dict
                # ydl.prepare_filename(info_dict) usually gives the path it *would* use
                # After download=True, the file should be at the location based on outtmpl
                # We need to find the exact downloaded file path.
                downloaded_file_path = None
                if info_dict and info_dict.get('_filename'): # yt-dlp version >= 2023.06.22 might use this
                    downloaded_file_path = info_dict['_filename']
                elif info_dict : # Older way, construct from template
                     downloaded_file_path = ydl.prepare_filename(info_dict)

                if downloaded_file_path and os.path.exists(downloaded_file_path):
                    logger.info(f"Video downloaded successfully for VSID {video_source_id} to: {downloaded_file_path}")
                    return downloaded_file_path
                else:
                    # Try to find the file in the temp_dir if info_dict didn't give precise path
                    found_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                    if found_files:
                        logger.info(f"Video downloaded for VSID {video_source_id}, found file: {found_files[0]} in {temp_dir}")
                        return os.path.join(temp_dir, found_files[0])
                    logger.error(f"Video download attempted for VSID {video_source_id} but file not found at expected path or in {temp_dir}. Info: {info_dict}")
                    return None

        except yt_dlp.utils.DownloadError as dl_err:
            logger.error(f"yt-dlp DownloadError for URL {video_url} (VSID {video_source_id}): {dl_err}")
            # Error message might contain info like "video unavailable", "private video" etc.
        except Exception as e:
            logger.error(f"Generic error downloading video {video_url} (VSID {video_source_id}): {e}", exc_info=True)
        
        # Cleanup temp dir if download failed early or file not found
        try:
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
        except Exception as cleanup_err:
            logger.error(f"Error cleaning up temp download directory {temp_dir}: {cleanup_err}")
            
        return None


    def analyze_video_content(self, video_source_model: VideoSource, raw_video_item_data: dict) -> dict:
        """
        Orchestrates content analysis (transcript and visual) for a given VideoSource.
        `video_source_model` is the Django ORM object.
        `raw_video_item_data` is the dictionary from SOIAgent.
        This method updates the `video_source_model` status based on analysis outcomes.
        """
        logger.info(f"ContentAnalysisAgent: Starting analysis for VideoSource ID {video_source_model.id}, Title: {video_source_model.video.title[:50]}")
        
        overall_analysis_report = {
            "video_source_id": video_source_model.id,
            "transcript_analysis": None,
            "visual_analysis": None,
            "analysis_completed_at": None,
            "errors": []
        }
        
        has_errors = False

        # --- 1. Transcript Analysis ---
        # Check if transcript data is available or can be fetched by TranscriptAnalyzer
        # TranscriptAnalyzer's process_transcript_for_video_source handles fetching VTT if URL provided.
        if raw_video_item_data.get('transcript_text') or raw_video_item_data.get('transcript_vtt_url'):
            video_source_model.processing_status = 'transcript_processing'
            video_source_model.save(update_fields=['processing_status', 'updated_at'])
            logger.debug(f"VSID {video_source_model.id}: Starting transcript analysis.")
            try:
                transcript_results = self.transcript_analyzer.process_transcript_for_video_source(
                    video_source_model,
                    raw_video_item_data
                )
                overall_analysis_report["transcript_analysis"] = transcript_results
                if transcript_results.get("errors"):
                    has_errors = True
                    overall_analysis_report["errors"].extend(transcript_results["errors"])
                    video_source_model.processing_error_message = (video_source_model.processing_error_message or "") + \
                                                                  f"Transcript errors: {'; '.join(transcript_results['errors'][:2])}. "
                logger.info(f"VSID {video_source_model.id}: Transcript analysis finished.")
                video_source_model.processing_status = 'transcript_processed' # Intermediate status

            except Exception as e:
                logger.error(f"Critical error during transcript analysis for VSID {video_source_model.id}: {e}", exc_info=True)
                has_errors = True
                err_msg = f"Transcript analysis critical error: {str(e)}"
                overall_analysis_report["errors"].append(err_msg)
                video_source_model.processing_error_message = (video_source_model.processing_error_message or "") + err_msg + ". "
                video_source_model.processing_status = 'processing_failed'
        else:
            logger.info(f"VSID {video_source_model.id}: No transcript data provided by SOIAgent. Skipping transcript analysis.")
            overall_analysis_report["transcript_analysis"] = {"status": "skipped", "message": "No transcript data available."}
            # No error state here, just skipped. Visual analysis might still proceed.
            video_source_model.processing_status = 'metadata_fetched' # Or a more specific status


        # --- 2. Visual Analysis ---
        # Visual analysis requires a local video file.
        # Check if SOIAgent provided a local path, or if we need to download it.
        local_video_file_path = raw_video_item_data.get('local_file_path') # SOIAgent might provide this
        temp_download_dir_for_cleanup = None

        if not local_video_file_path and video_source_model.original_url:
            # Attempt to download the video for visual analysis
            logger.info(f"VSID {video_source_model.id}: No local file path for visual analysis. Attempting download from {video_source_model.original_url}")
            video_source_model.meta_visual_processing_status = 'visual_downloading' # Custom status
            video_source_model.save(update_fields=['meta_visual_processing_status', 'updated_at'])
            
            local_video_file_path = self._download_video_if_needed(video_source_model.original_url, video_source_model.id)
            if local_video_file_path:
                temp_download_dir_for_cleanup = os.path.dirname(local_video_file_path) # Store parent dir for cleanup
        
        if local_video_file_path and os.path.exists(local_video_file_path):
            video_source_model.meta_visual_processing_status = 'visual_processing' # Standard status
            video_source_model.save(update_fields=['meta_visual_processing_status', 'updated_at'])
            logger.debug(f"VSID {video_source_model.id}: Starting visual analysis from path: {local_video_file_path}")
            try:
                visual_results = self.visual_analyzer.process_video_frames(
                    video_source_model,
                    local_video_file_path,
                    frame_interval_sec=2 # Example interval
                )
                overall_analysis_report["visual_analysis"] = visual_results
                if visual_results.get("errors"):
                    has_errors = True
                    overall_analysis_report["errors"].extend(visual_results["errors"])
                    video_source_model.meta_visual_processing_error = (video_source_model.meta_visual_processing_error or "") + \
                                                                     f"Visual errors: {'; '.join(visual_results['errors'][:2])}. "
                logger.info(f"VSID {video_source_model.id}: Visual analysis finished.")
                video_source_model.meta_visual_processing_status = 'visual_processed'
                video_source_model.last_visual_indexed_at = timezone.now()

            except Exception as e:
                logger.error(f"Critical error during visual analysis for VSID {video_source_model.id}: {e}", exc_info=True)
                has_errors = True
                err_msg = f"Visual analysis critical error: {str(e)}"
                overall_analysis_report["errors"].append(err_msg)
                video_source_model.meta_visual_processing_error = (video_source_model.meta_visual_processing_error or "") + err_msg + ". "
                video_source_model.meta_visual_processing_status = 'processing_failed'
            finally:
                # Clean up downloaded video file and its temp directory
                if temp_download_dir_for_cleanup and os.path.exists(temp_download_dir_for_cleanup):
                    try:
                        import shutil
                        shutil.rmtree(temp_download_dir_for_cleanup)
                        logger.info(f"Cleaned up temporary download directory: {temp_download_dir_for_cleanup} for VSID {video_source_model.id}")
                    except Exception as e:
                        logger.error(f"Error cleaning up temp dir {temp_download_dir_for_cleanup}: {e}", exc_info=True)
        else:
            logger.info(f"VSID {video_source_model.id}: No local video file available or download failed. Skipping visual analysis.")
            overall_analysis_report["visual_analysis"] = {"status": "skipped", "message": "No local video file for analysis."}
            video_source_model.meta_visual_processing_status = 'pending' # Or 'skipped' if you have such status


        # --- Finalize ---
        if has_errors:
            # If any sub-analysis had critical errors, mark overall as failed.
            # Specific error messages are already on video_source_model.
            if video_source_model.processing_status != 'processing_failed' and \
               video_source_model.meta_visual_processing_status != 'processing_failed':
                 # If not already marked as fully failed by a sub-process
                 video_source_model.processing_status = 'processing_failed' 
                 video_source_model.processing_error_message = (video_source_model.processing_error_message or "") + "One or more analysis steps failed. "

        elif video_source_model.processing_status == 'transcript_processed' and \
             video_source_model.meta_visual_processing_status in ['visual_processed', 'pending', 'skipped']:
            # If transcript processed and visual is either done, skipped, or was never needed
            video_source_model.processing_status = 'analysis_complete'
            video_source_model.processing_error_message = None # Clear errors if successful
            video_source_model.last_analyzed_at = timezone.now()
            overall_analysis_report["analysis_completed_at"] = video_source_model.last_analyzed_at.isoformat()
        
        # Save final status of VideoSource model
        video_source_model.save(update_fields=[
            'processing_status', 'processing_error_message', 'last_analyzed_at',
            'meta_visual_processing_status', 'meta_visual_processing_error', 'last_visual_indexed_at'
        ])
        
        logger.info(f"ContentAnalysisAgent: Finished ALL analysis for VideoSource ID {video_source_model.id}. Final status: {video_source_model.processing_status}, Visual status: {video_source_model.meta_visual_processing_status}")
        return overall_analysis_report
