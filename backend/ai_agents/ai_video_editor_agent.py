# backend/ai_agents/ai_video_editor_agent.py
import logging
import os
import uuid
import tempfile
import shutil # For cleaning up temporary directories
import re

from moviepy.editor import VideoFileClip, concatenate_videoclips, TextClip, CompositeVideoClip
# For more advanced audio: from pydub import AudioSegment
# For subtitles: might need custom SRT parsing or integration with Whisper-like models if generating them
import yt_dlp # For downloading source video if URL is provided

from django.conf import settings
# from api.models import EditTask # Avoid direct model imports if possible, or handle carefully

logger = logging.getLogger(__name__)

# --- Helper Functions for Video Editing ---

def _parse_time_string(time_str: str) -> float | None:
    """Converts HH:MM:SS.mmm or MM:SS.mmm or SS.mmm to seconds."""
    if not time_str: return None
    parts = time_str.split(':')
    try:
        if len(parts) == 3: # HH:MM:SS.mmm
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2: # MM:SS.mmm
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1: # SS.mmm
            return float(parts[0])
    except ValueError:
        logger.warning(f"Invalid time string format: {time_str}")
    return None

def _download_video_for_editing(video_url: str, edit_task_id_for_naming: str) -> str | None:
    """Downloads a video from a URL to a temporary local file for editing."""
    if not video_url: return None
    
    # Create a unique temporary directory for this download
    temp_dir = tempfile.mkdtemp(prefix=f"papri_edit_dl_{edit_task_id_for_naming}_")
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best', # Prefer 1080p mp4
        'outtmpl': os.path.join(temp_dir, f'%(id)s_edit_source.%(ext)s'),
        'quiet': True,
        'logger': logging.getLogger(f"{__name__}.yt_dlp_edit_dl"),
        'noplaylist': True,
        'noprogress': True,
    }
    
    logger.info(f"EditorAgent: Attempting to download video for editing from URL: {video_url} (Task: {edit_task_id_for_naming}) to {temp_dir}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            downloaded_file_path = ydl.prepare_filename(info_dict) if info_dict else None

            if downloaded_file_path and os.path.exists(downloaded_file_path):
                logger.info(f"EditorAgent: Video for editing downloaded successfully (Task: {edit_task_id_for_naming}) to: {downloaded_file_path}")
                return downloaded_file_path # This path includes the temp_dir
            else:
                found_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if found_files:
                    full_p = os.path.join(temp_dir, found_files[0])
                    logger.info(f"EditorAgent: Video for editing downloaded (Task: {edit_task_id_for_naming}), found file: {full_p}")
                    return full_p
                logger.error(f"EditorAgent: Video download for editing attempted (Task: {edit_task_id_for_naming}) but file not found. Info: {info_dict}")
                shutil.rmtree(temp_dir) # Clean up if download failed to produce file
                return None
    except Exception as e:
        logger.error(f"EditorAgent: Error downloading video {video_url} for editing (Task: {edit_task_id_for_naming}): {e}", exc_info=True)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir) # Cleanup
        return None


class AIVideoEditorAgent:
    def __init__(self):
        # Initialize any models or resources needed for prompt understanding or advanced editing.
        # For example, an NLP model for parsing edit commands.
        # self.nlp_parser = ...
        logger.info("AIVideoEditorAgent initialized.")

    def _interpret_prompt(self, prompt: str, video_duration: float) -> List[Dict[str, Any]]:
        """
        Interprets the natural language prompt into a list of actionable editing commands.
        This is the core AI challenge. For now, we'll use simple regex/keyword matching.
        
        Returns a list of command dicts, e.g.:
        [
            {'action': 'cut', 'params': {'start_sec': 0, 'end_sec': 5}},
            {'action': 'add_text', 'params': {'text': 'Hello', 'start_sec': 6, 'duration_sec': 3, 'position': ('center', 'center')}},
            {'action': 'remove_silence', 'params': {'threshold_db': -40, 'min_silence_len_ms': 500}},
            {'action': 'replace_background', 'params': {'new_bg_color': 'green'}}, (very advanced)
            {'action': 'create_montage', 'params': {'theme': 'cat scenes'}} (very advanced)
        ]
        """
        commands = []
        prompt_lower = prompt.lower()

        # Example: "cut from 10s to 20s" or "remove first 5 seconds" or "delete between 1:00 and 1:05"
        cut_match = re.search(r"(cut|remove|delete)\s*(?:from\s*)?([\d.:]+)\s*(?:to|and|-)\s*([\d.:]+)", prompt_lower)
        if cut_match:
            action_verb, start_str, end_str = cut_match.groups()
            start_sec = _parse_time_string(start_str)
            end_sec = _parse_time_string(end_str)
            if start_sec is not None and end_sec is not None and start_sec < end_sec:
                # 'cut' usually means keep everything EXCEPT this segment.
                # Or, if "remove/delete", it means remove this segment. Let's assume remove.
                commands.append({'action': 'cut_segment', 'params': {'start_sec': start_sec, 'end_sec': end_sec, 'remove': True}})
        
        cut_first_match = re.search(r"(cut|remove|delete)\s*first\s*([\d.]+)\s*seconds?", prompt_lower)
        if cut_first_match:
            _, duration_str = cut_first_match.groups()
            duration_sec = _parse_time_string(duration_str)
            if duration_sec is not None:
                 commands.append({'action': 'cut_segment', 'params': {'start_sec': 0, 'end_sec': duration_sec, 'remove': True}})

        cut_last_match = re.search(r"(cut|remove|delete)\s*last\s*([\d.]+)\s*seconds?", prompt_lower)
        if cut_last_match:
            _, duration_str = cut_last_match.groups()
            duration_sec = _parse_time_string(duration_str)
            if duration_sec is not None and video_duration > duration_sec:
                 commands.append({'action': 'cut_segment', 'params': {'start_sec': video_duration - duration_sec, 'end_sec': video_duration, 'remove': True}})


        # Example: "add text 'Hello World' at 5s for 3s"
        text_match = re.search(r"add text\s*['\"]([^'\"]+)['\"]\s*(?:at\s*([\d.:]+))?\s*(?:for\s*([\d.:]+)\s*seconds?)?", prompt_lower)
        if text_match:
            text_content, start_str, duration_str = text_match.groups()
            start_sec = _parse_time_string(start_str) if start_str else 0
            duration_sec = _parse_time_string(duration_str) if duration_str else 3 # Default duration
            if text_content and start_sec is not None and duration_sec is not None:
                commands.append({
                    'action': 'add_text', 
                    'params': {
                        'text': text_content, 
                        'start_sec': start_sec, 
                        'duration_sec': duration_sec,
                        'fontsize': 24, # Default
                        'color': 'white', # Default
                        'position': ('center', 'bottom'), # Default
                        'margin_y': 10
                    }
                })
        
        # Placeholder for more complex commands
        if "remove silence" in prompt_lower:
            commands.append({'action': 'remove_silence', 'params': {'threshold_db': -35, 'min_duration_ms': 300}}) # Params are examples
        
        if "add background music" in prompt_lower:
            # This would require a music file or selection mechanism
            commands.append({'action': 'add_background_music', 'params': {'music_file': 'default_music.mp3'}}) # Placeholder

        if not commands:
            logger.warning(f"EditorAgent: Could not interpret prompt into actionable commands: '{prompt}'")
            # Return a "no_op" or error command if nothing understood
            commands.append({'action': 'no_op', 'params': {'reason': 'Could not understand prompt.'}})

        return commands

    def _apply_edit_commands(self, input_video_path: str, commands: List[Dict[str, Any]]) -> VideoFileClip | None:
        """
        Applies a list of parsed edit commands to the video using MoviePy.
        """
        try:
            current_clip = VideoFileClip(input_video_path)
            logger.info(f"EditorAgent: Loaded video '{input_video_path}' for editing. Duration: {current_clip.duration}s")
        except Exception as e:
            logger.error(f"EditorAgent: Failed to load video file '{input_video_path}' with MoviePy: {e}", exc_info=True)
            return None

        subclips_to_keep = []
        last_cut_end = 0.0

        # Phase 1: Handle 'cut_segment' (remove=True) by defining subclips to keep
        # Sort cut commands by start time to process them logically
        cut_commands = sorted([cmd for cmd in commands if cmd['action'] == 'cut_segment' and cmd['params'].get('remove')], 
                              key=lambda c: c['params']['start_sec'])
        
        for cmd in cut_commands:
            params = cmd['params']
            start_sec = params['start_sec']
            end_sec = params['end_sec']

            if start_sec < last_cut_end: # Overlapping cut, adjust start to avoid issues
                start_sec = last_cut_end
            
            if start_sec < end_sec: # Valid cut segment
                if start_sec > last_cut_end: # There's a segment to keep before this cut
                    subclips_to_keep.append(current_clip.subclip(last_cut_end, start_sec))
                last_cut_end = end_sec # Move pointer past the removed segment
        
        # Add the final segment after all cuts
        if last_cut_end < current_clip.duration:
            subclips_to_keep.append(current_clip.subclip(last_cut_end, current_clip.duration))
        
        if cut_commands and subclips_to_keep: # If cuts were made
            if not subclips_to_keep: # All video was cut
                logger.warning("EditorAgent: All video content was cut based on commands.")
                # Create a very short black clip or handle as error
                return TextClip("All content removed", fontsize=30, color='white', bg_color='black', size=current_clip.size).set_duration(1)
            current_clip = concatenate_videoclips(subclips_to_keep)
            logger.info(f"EditorAgent: Applied cuts. New duration: {current_clip.duration}s")
        elif cut_commands and not subclips_to_keep : # All video cut
             logger.warning("EditorAgent: All video content was cut based on commands (no subclips to keep).")
             return TextClip("Content removed", fontsize=30, color='white', bg_color='black', size=current_clip.size).set_duration(1)


        # Phase 2: Apply other effects (like add_text) to the potentially modified clip
        text_clips_to_composite = [current_clip] # Start with base video

        for cmd in commands:
            action = cmd['action']
            params = cmd['params']

            if action == 'add_text':
                try:
                    txt_clip = TextClip(
                        params['text'], 
                        fontsize=params.get('fontsize', 24), 
                        color=params.get('color', 'white'),
                        font='Arial', # Specify a font available on the system
                        bg_color=params.get('bg_color', 'transparent'), # e.g. 'black' with some opacity
                        # stroke_color='black', stroke_width=1 # Example for outline
                    )
                    txt_clip = txt_clip.set_position(params.get('position', ('center', 'bottom'))) \
                                     .set_duration(params['duration_sec']) \
                                     .set_start(params['start_sec'])
                    
                    # Adjust position with margin if specified (MoviePy positions from top-left for some pos strings)
                    if params.get('position') == ('center', 'bottom') and params.get('margin_y'):
                         txt_clip = txt_clip.set_position(lambda t: ('center', current_clip.h - txt_clip.h - params['margin_y']))


                    # Ensure text clip does not exceed main clip duration
                    if txt_clip.end > current_clip.duration:
                        txt_clip = txt_clip.set_duration(current_clip.duration - txt_clip.start)
                    
                    if txt_clip.duration > 0:
                        text_clips_to_composite.append(txt_clip)
                        logger.info(f"EditorAgent: Added text '{params['text']}' from {params['start_sec']}s for {params['duration_sec']}s")
                except Exception as e:
                    logger.error(f"EditorAgent: Error adding text '{params.get('text')}': {e}", exc_info=True)
            
            elif action == 'remove_silence':
                logger.warning("EditorAgent: 'remove_silence' action is a placeholder and not fully implemented.")
                # This would require integrating audio analysis (e.g., librosa, pydub)
                # to find silent segments and then reconstruct video/audio without them.
            
            elif action == 'add_background_music':
                logger.warning("EditorAgent: 'add_background_music' action is a placeholder.")
                # Requires loading an AudioClip, adjusting volume, and compositing with video's audio.

        if len(text_clips_to_composite) > 1:
            final_clip = CompositeVideoClip(text_clips_to_composite, size=current_clip.size)
            return final_clip
        
        return current_clip # Return original or cut clip if no other effects applied

    def perform_edit(self, video_path_or_url: str, prompt: str, edit_task_id_for_agent: str) -> dict:
        """
        Main method to perform video editing.
        `video_path_or_url`: Can be a local file path or a URL (will be downloaded if URL).
        `prompt`: User's text instruction.
        `edit_task_id_for_agent`: Used for naming output files and temp dirs.

        Returns a dict:
        {'status': 'completed', 'output_media_path': 'relative/path/to/output.mp4', 'output_preview_url': None}
        or {'status': 'failed', 'error': 'Error message'}
        'output_media_path' is relative to Django's MEDIA_ROOT.
        """
        logger.info(f"AIVideoEditorAgent: Received request for Task {edit_task_id_for_agent}. Prompt: '{prompt[:100]}...'. Video: {video_path_or_url}")

        input_video_path = None
        temp_download_dir_for_cleanup = None # If video was downloaded

        if video_path_or_url.startswith("http://") or video_path_or_url.startswith("https://"):
            input_video_path = _download_video_for_editing(video_path_or_url, edit_task_id_for_agent)
            if input_video_path:
                temp_download_dir_for_cleanup = os.path.dirname(input_video_path) # Parent of the downloaded file
        elif os.path.exists(video_path_or_url):
            input_video_path = video_path_or_url
        else:
            logger.error(f"EditorAgent: Input video path/URL is invalid or file not found: {video_path_or_url}")
            return {"status": "failed", "error": "Input video path or URL is invalid or file not found."}

        if not input_video_path:
            return {"status": "failed", "error": "Failed to obtain input video for editing."}

        # Create a temporary directory for the output video
        # Output relative to MEDIA_ROOT: 'edited_videos/user_X_or_task_Y/output_uuid.mp4'
        output_dir_name = os.path.join('edited_videos', f"task_{edit_task_id_for_agent}")
        output_dir_full_path = os.path.join(settings.MEDIA_ROOT, output_dir_name)
        os.makedirs(output_dir_full_path, exist_ok=True)
        
        output_filename_base = f"edited_output_{uuid.uuid4().hex[:8]}"
        output_video_relative_path = os.path.join(output_dir_name, f"{output_filename_base}.mp4")
        output_video_full_path = os.path.join(output_dir_full_path, f"{output_filename_base}.mp4")

        try:
            # Get video duration for prompt interpretation context
            temp_clip_for_duration = VideoFileClip(input_video_path)
            video_duration = temp_clip_for_duration.duration
            temp_clip_for_duration.close()

            edit_commands = self._interpret_prompt(prompt, video_duration)
            if not edit_commands or edit_commands[0].get('action') == 'no_op':
                error_msg = edit_commands[0]['params'].get('reason', 'Could not understand editing prompt.')
                logger.warning(f"EditorAgent Task {edit_task_id_for_agent}: {error_msg}")
                return {"status": "failed", "error": error_msg}

            logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Interpreted commands: {edit_commands}")
            
            edited_clip = self._apply_edit_commands(input_video_path, edit_commands)

            if edited_clip:
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits successful. Writing output to {output_video_full_path}")
                # Write the video. Choose codec, bitrate, audio_codec carefully for quality/size.
                # preset='medium' is a balance. 'ultrafast' is quicker but larger.
                # threads can speed up writing.
                edited_clip.write_videofile(
                    output_video_full_path, 
                    codec='libx264',    # Common, good quality
                    audio_codec='aac',  # Common audio codec
                    temp_audiofile=os.path.join(output_dir_full_path, f"{output_filename_base}_temp_audio.m4a"), # MoviePy needs this
                    remove_temp=True,
                    threads=4,          # Use multiple threads
                    preset='medium',    # ffmpeg preset
                    logger='bar'        # Progress bar logger from MoviePy
                )
                edited_clip.close()
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Video successfully edited and saved to {output_video_relative_path}")
                
                return {
                    "status": "completed",
                    "output_media_path": output_video_relative_path, # Path relative to MEDIA_ROOT
                    "output_preview_url": None # Could generate a GIF preview here if needed
                }
            else:
                logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits resulted in no video clip.")
                return {"status": "failed", "error": "Editing process failed to produce a video."}

        except Exception as e:
            logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Critical error during video editing: {e}", exc_info=True)
            return {"status": "failed", "error": f"An unexpected error occurred during video editing: {str(e)}"}
        finally:
            # Clean up the originally downloaded video and its temp directory if it was created by this agent
            if temp_download_dir_for_cleanup and os.path.exists(temp_download_dir_for_cleanup):
                try:
                    shutil.rmtree(temp_download_dir_for_cleanup)
                    logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Cleaned up temporary download directory: {temp_download_dir_for_cleanup}")
                except Exception as e_clean:
                    logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Error cleaning up temp download dir {temp_download_dir_for_cleanup}: {e_clean}", exc_info=True)
            # Input_video_path might be a user-provided path not to be deleted by this agent if not downloaded by it.
