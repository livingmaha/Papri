# backend/ai_agents/ai_video_editor_agent.py
import logging
import os
import uuid
import tempfile
import shutil # For cleaning up temporary directories
import re
from typing import List, Dict, Any, Optional # Added typing

from moviepy.editor import VideoFileClip, concatenate_videoclips, TextClip, CompositeVideoClip
# For more advanced audio: from pydub import AudioSegment
# For subtitles: might need custom SRT parsing or integration with Whisper-like models if generating them
import yt_dlp # For downloading source video if URL is provided

from django.conf import settings
# from api.models import EditTask # Avoid direct model imports if possible, or handle carefully

logger = logging.getLogger(__name__)

# --- Helper Functions for Video Editing ---

def _parse_time_string(time_str: str) -> Optional[float]: # Return type hint added
    """
    Converts HH:MM:SS.mmm, MM:SS.mmm, or SS.mmm to seconds.
    Returns None if parsing fails.
    """
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

def _download_video_for_editing(video_url: str, edit_task_id_for_naming: str) -> Optional[str]: # Return type hint
    """Downloads a video from a URL to a temporary local file for editing."""
    if not video_url: return None
    
    temp_dir = tempfile.mkdtemp(prefix=f"papri_edit_dl_{edit_task_id_for_naming}_")
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best',
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
                return downloaded_file_path
            else:
                found_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if found_files:
                    full_p = os.path.join(temp_dir, found_files[0])
                    logger.info(f"EditorAgent: Video for editing downloaded (Task: {edit_task_id_for_naming}), found file: {full_p}")
                    return full_p
                logger.error(f"EditorAgent: Video download for editing attempted (Task: {edit_task_id_for_naming}) but file not found. Info: {info_dict}")
                shutil.rmtree(temp_dir)
                return None
    except Exception as e:
        logger.error(f"EditorAgent: Error downloading video {video_url} for editing (Task: {edit_task_id_for_naming}): {e}", exc_info=True)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        return None


class AIVideoEditorAgent:
    """
    AIVideoEditorAgent handles interpreting user prompts for video editing
    and applying those edits using MoviePy.

    Initial supported commands (MVP Focus for content creators):
    1.  `CUT FROM <timestamp> TO <timestamp>`
        Removes the segment between the two timestamps.
        Example: "CUT FROM 00:10 TO 00:25.5" or "CUT FROM 5s TO 10s"

    2.  `ADD TEXT "<text>" AT <timestamp> DURATION <seconds> FONTSIZE <size> COLOR <color>`
        Overlays text on the video. Fontsize and color are optional.
        Timestamp is the start time of the text. Duration is how long it stays.
        Example: "ADD TEXT "Hello World" AT 5s DURATION 3s FONTSIZE 48 COLOR blue"
        Example: "ADD TEXT "Chapter 1" AT 00:00 DURATION 5s"

    3.  `MUTE AUDIO FROM <timestamp> TO <timestamp>`
        Mutes the audio for the specified segment.
        Example: "MUTE AUDIO FROM 1:00 TO 1:05"

    4.  `REPLACE AUDIO WITH <new_audio_file_url> FROM <timestamp> TO <timestamp>` (Placeholder)
        Replaces the audio in a segment with audio from a new file/URL.
        Timestamp parameters might be omitted to replace entire audio.
        *Note: This is a more complex command, initially stubbed for intent recognition.*
        Example: "REPLACE AUDIO WITH http://example.com/music.mp3"

    5.  `CREATE HIGHLIGHT REEL DURATION <seconds>` (Placeholder)
        Attempts to create a highlight reel of a specified duration.
        *Note: This is a very advanced command, initially stubbed for intent recognition.*
        Example: "CREATE HIGHLIGHT REEL DURATION 30s"

    Timestamp format: Accepts "HH:MM:SS.mmm", "MM:SS.mmm", "SS.mmm", or just "S" (e.g., "5s", "10.5s").
    Color names: Standard web color names (e.g., "white", "black", "red", "blue", "green", "#FF00FF").
    """
    def __init__(self):
        logger.info("AIVideoEditorAgent initialized.")

    def _interpret_prompt(self, prompt: str, video_duration: float) -> List[Dict[str, Any]]:
        """
        Interprets the natural language prompt into a list of actionable editing commands.
        Focuses on a defined set of commands for the MVP.
        """
        commands = []
        prompt_lower = prompt.lower()

        # Command: CUT FROM <timestamp> TO <timestamp>
        # Regex captures "cut from X to Y" or "delete from X to Y" etc.
        cut_match = re.search(r"(cut|remove|delete)\s*(?:segment|part|portion)?\s*from\s*([\d.:s]+)\s*to\s*([\d.:s]+)", prompt_lower)
        if cut_match:
            _, start_str, end_str = cut_match.groups()
            start_sec = _parse_time_string(start_str.replace('s', ''))
            end_sec = _parse_time_string(end_str.replace('s', ''))
            if start_sec is not None and end_sec is not None and start_sec < end_sec:
                commands.append({'action': 'cut_segment', 'params': {'start_sec': start_sec, 'end_sec': end_sec, 'remove': True}})
                logger.info(f"Interpreted command: CUT from {start_sec}s to {end_sec}s")


        # Command: ADD TEXT "<text>" AT <timestamp> DURATION <seconds> FONTSIZE <size> COLOR <color>
        # Regex for: ADD TEXT "text content" AT 5s DURATION 3s FONTSIZE 24 COLOR white
        text_match = re.search(
            r"add text\s*\"([^\"]+)\"\s*at\s*([\d.:s]+)\s*(?:duration\s*([\d.:s]+))?"
            r"(?:\s*fontsize\s*(\d+))?(?:\s*color\s*([a-zA-Z#\d]+))?", prompt_lower
        )
        if text_match:
            text_content, start_str, duration_str, fontsize_str, color_str = text_match.groups()
            start_sec = _parse_time_string(start_str.replace('s', ''))
            duration_sec = _parse_time_string(duration_str.replace('s', '')) if duration_str else 3.0 # Default 3s duration
            
            params = {
                'text': text_content,
                'start_sec': start_sec,
                'duration_sec': duration_sec,
                'fontsize': int(fontsize_str) if fontsize_str else 24,
                'color': color_str if color_str else 'white',
                'position': ('center', 'bottom'), 'margin_y': 20 # Default position
            }
            if params['start_sec'] is not None and params['duration_sec'] is not None:
                commands.append({'action': 'add_text', 'params': params})
                logger.info(f"Interpreted command: ADD TEXT with params {params}")

        # Command: MUTE AUDIO FROM <timestamp> TO <timestamp>
        mute_match = re.search(r"mute audio\s*from\s*([\d.:s]+)\s*to\s*([\d.:s]+)", prompt_lower)
        if mute_match:
            start_str, end_str = mute_match.groups()
            start_sec = _parse_time_string(start_str.replace('s', ''))
            end_sec = _parse_time_string(end_str.replace('s', ''))
            if start_sec is not None and end_sec is not None and start_sec < end_sec:
                commands.append({'action': 'mute_audio', 'params': {'start_sec': start_sec, 'end_sec': end_sec}})
                logger.info(f"Interpreted command: MUTE AUDIO from {start_sec}s to {end_sec}s")

        # Command: REPLACE AUDIO WITH <url> [FROM <timestamp> TO <timestamp>] (Placeholder Intent)
        replace_audio_match = re.search(r"replace audio with\s*(\S+)(?:\s*from\s*([\d.:s]+)\s*to\s*([\d.:s]+))?", prompt_lower)
        if replace_audio_match:
            audio_url, start_str, end_str = replace_audio_match.groups()
            start_sec = _parse_time_string(start_str.replace('s', '')) if start_str else 0
            end_sec = _parse_time_string(end_str.replace('s', '')) if end_str else video_duration
            commands.append({'action': 'replace_audio_stub', 'params': {'audio_url': audio_url, 'start_sec': start_sec, 'end_sec': end_sec}})
            logger.info(f"Interpreted command (STUB): REPLACE AUDIO with {audio_url} from {start_sec}s to {end_sec}s")

        # Command: CREATE HIGHLIGHT REEL DURATION <seconds> (Placeholder Intent)
        highlight_match = re.search(r"create highlight reel\s*(?:duration\s*([\d.:s]+))?", prompt_lower)
        if highlight_match:
            duration_str = highlight_match.group(1)
            duration_sec = _parse_time_string(duration_str.replace('s', '')) if duration_str else 30.0 # Default 30s
            commands.append({'action': 'create_highlight_reel_stub', 'params': {'duration_sec': duration_sec}})
            logger.info(f"Interpreted command (STUB): CREATE HIGHLIGHT REEL duration {duration_sec}s")


        # Fallback for unmatched commands or if no commands parsed
        if not commands:
            logger.warning(f"EditorAgent: Could not interpret prompt into any defined MVP commands: '{prompt}'")
            # Log unrecognized prompts
            # For MVP, if it's not one of the above, it's an error or "no_op"
            commands.append({'action': 'no_op', 'params': {'reason': f"Could not understand prompt. Supported commands: CUT, ADD TEXT, MUTE AUDIO. Prompt received: '{prompt[:100]}...'"}})
        
        return commands

    def _apply_edit_commands(self, input_video_path: str, commands: List[Dict[str, Any]]) -> Optional[VideoFileClip]: # Return type hint
        """
        Applies a list of parsed edit commands to the video using MoviePy.
        Refined to handle new commands and placeholders.
        """
        try:
            current_clip = VideoFileClip(input_video_path)
            logger.info(f"EditorAgent: Loaded video '{input_video_path}' for editing. Duration: {current_clip.duration}s")
        except Exception as e:
            logger.error(f"EditorAgent: Failed to load video file '{input_video_path}' with MoviePy: {e}", exc_info=True)
            return None

        # --- Store original audio separately for MUTE or REPLACE operations ---
        original_audio = current_clip.audio 

        # --- Phase 1: Handle 'cut_segment' (remove=True) ---
        subclips_to_keep = []
        last_cut_end = 0.0
        cut_commands = sorted([cmd for cmd in commands if cmd['action'] == 'cut_segment' and cmd['params'].get('remove')], 
                              key=lambda c: c['params']['start_sec'])
        
        current_video_duration_for_cuts = current_clip.duration
        for cmd in cut_commands:
            params = cmd['params']
            start_sec = max(0, params['start_sec']) # Ensure non-negative
            end_sec = min(current_video_duration_for_cuts, params['end_sec']) # Ensure within bounds

            if start_sec < last_cut_end: start_sec = last_cut_end
            if start_sec < end_sec:
                if start_sec > last_cut_end:
                    subclips_to_keep.append(current_clip.subclip(last_cut_end, start_sec))
                last_cut_end = end_sec
        
        if last_cut_end < current_video_duration_for_cuts:
            subclips_to_keep.append(current_clip.subclip(last_cut_end, current_video_duration_for_cuts))
        
        if cut_commands:
            if not subclips_to_keep:
                logger.warning("EditorAgent: All video content was cut.")
                # Return a very short black clip or handle as error (as per existing logic)
                current_clip.close()
                return TextClip("All content removed", fontsize=30, color='white', bg_color='black', size=(current_clip.size or (640,360))).set_duration(1)
            
            new_clip_without_audio = concatenate_videoclips([sc.without_audio() for sc in subclips_to_keep])
             # The audio needs to be reconstructed carefully if cuts are made.
            # This is complex. For simplicity, if cuts happen, audio might become desynced or be from the first segment.
            # A robust solution would involve cutting and concatenating audio segments corresponding to video segments.
            # For now, let's try to assign the audio of the *newly formed* clip.
            # If cuts were made, the audio needs to be re-stitched or taken from the dominant segment.
            # This is a simplification:
            if subclips_to_keep:
                 current_clip = concatenate_videoclips(subclips_to_keep) # This will carry over audio from subclips
            logger.info(f"EditorAgent: Applied cuts. New duration: {current_clip.duration}s")


        # --- Phase 2: Apply audio effects (MUTE, REPLACE_AUDIO_STUB) ---
        modified_audio_clip = current_clip.audio # Start with current audio (potentially after cuts)

        for cmd in commands:
            action = cmd['action']
            params = cmd['params']

            if action == 'mute_audio' and modified_audio_clip:
                # This is a simplified mute; MoviePy doesn't have a direct "mute segment".
                # One way is to create silent audio for that part and composite.
                # Or, if affecting the whole clip's audio track:
                start_mute = params['start_sec']
                end_mute = params['end_sec']
                # More robust muting would involve sub-clipping audio, creating silence, and concatenating.
                # For a simple approach if affecting entire current_clip's audio:
                if start_mute == 0 and end_mute >= current_clip.duration: # Mute whole clip
                    current_clip = current_clip.without_audio()
                    modified_audio_clip = None # No audio left
                    logger.info(f"EditorAgent: Muted audio for entire clip (duration {current_clip.duration}s)")
                else:
                    # Segmented muting is more complex with MoviePy's main API.
                    # Requires audio subclip, silence, concatenate. Not implemented in this pass.
                    logger.warning(f"EditorAgent: Segmented audio mute from {start_mute} to {end_mute} is complex and not fully implemented. Muting entire clip as fallback if start=0, end=duration.")
                    # As a placeholder, if we want to mute a segment, it would be:
                    # audio_part1 = modified_audio_clip.subclip(0, start_mute) if start_mute > 0 else None
                    # audio_part2 = modified_audio_clip.subclip(end_mute) if end_mute < modified_audio_clip.duration else None
                    # silent_segment = AudioClip(lambda t: 0, duration=end_mute-start_mute, fps=modified_audio_clip.fps if modified_audio_clip else 44100)
                    # clips_to_concat = [c for c in [audio_part1, silent_segment, audio_part2] if c]
                    # if clips_to_concat: modified_audio_clip = concatenate_audioclips(clips_to_concat)
                    # current_clip = current_clip.set_audio(modified_audio_clip)

            elif action == 'replace_audio_stub':
                logger.warning(f"EditorAgent: 'replace_audio_stub' action is a placeholder. Audio not replaced. Original audio kept or affected by other ops.")
                # Actual implementation would download audio_url, load as AudioClip, and set it.
                # If segment specific: current_clip.subclip(0, params['start_sec']).set_audio(new_audio.subclip(...)) ...

        if modified_audio_clip is not None and current_clip.audio != modified_audio_clip : # If audio was changed (e.g. by full mute)
            current_clip = current_clip.set_audio(modified_audio_clip)
        elif modified_audio_clip is None and current_clip.audio is not None: # Muted fully
            current_clip = current_clip.without_audio()


        # --- Phase 3: Apply visual effects (like add_text) ---
        text_clips_to_composite = [] # Start with an empty list for compositing

        for cmd in commands:
            action = cmd['action']
            params = cmd['params']

            if action == 'add_text':
                try:
                    txt_clip = TextClip(
                        params['text'], 
                        fontsize=params.get('fontsize', 24), 
                        color=params.get('color', 'white'),
                        font=params.get('font', 'Arial'), # Specify a font available
                        bg_color=params.get('bg_color', 'transparent'),
                        # stroke_color='black', stroke_width=1 # Example outline
                    )
                    txt_clip = txt_clip.set_position(params.get('position', ('center', 'bottom'))) \
                                     .set_duration(params['duration_sec']) \
                                     .set_start(params['start_sec'])
                    
                    if params.get('position') == ('center', 'bottom') and params.get('margin_y'):
                         txt_clip = txt_clip.set_position(lambda t: ('center', current_clip.h - txt_clip.h - params['margin_y']))

                    if txt_clip.end > current_clip.duration:
                        txt_clip = txt_clip.set_duration(current_clip.duration - txt_clip.start)
                    
                    if txt_clip.duration > 0:
                        text_clips_to_composite.append(txt_clip)
                        logger.info(f"EditorAgent: Prepared text '{params['text']}' from {params['start_sec']}s for {params['duration_sec']}s")
                except Exception as e:
                    logger.error(f"EditorAgent: Error preparing text clip '{params.get('text')}': {e}", exc_info=True)
            
            elif action == 'create_highlight_reel_stub':
                 logger.warning("EditorAgent: 'create_highlight_reel_stub' is a placeholder. No highlight reel created.")

        if text_clips_to_composite:
            # Composite text clips onto the current_clip
            # The base video clip for compositing should be `current_clip`
            final_composite_elements = [current_clip] + text_clips_to_composite
            final_clip = CompositeVideoClip(final_composite_elements, size=current_clip.size)
            current_clip.close() # Close original reference
            # If original_audio was stored and video was changed, ensure audio is correctly set
            # For CompositeVideoClip, audio usually comes from the first clip (current_clip here)
            # If current_clip's audio was already modified (e.g. muted), that should carry over.
            return final_clip
        
        return current_clip # Return original or cut/audio-modified clip if no other visual effects
        
    # perform_edit method largely remains the same, but will use the refined _interpret_prompt and _apply_edit_commands
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
        temp_download_dir_for_cleanup = None 

        if video_path_or_url.startswith("http://") or video_path_or_url.startswith("https://"):
            input_video_path = _download_video_for_editing(video_path_or_url, edit_task_id_for_agent)
            if input_video_path:
                temp_download_dir_for_cleanup = os.path.dirname(input_video_path) 
        elif os.path.exists(video_path_or_url):
            input_video_path = video_path_or_url
        else:
            logger.error(f"EditorAgent: Input video path/URL is invalid or file not found: {video_path_or_url}")
            return {"status": "failed", "error": "Input video path or URL is invalid or file not found."}

        if not input_video_path:
            return {"status": "failed", "error": "Failed to obtain input video for editing."}

        output_dir_name = os.path.join('edited_videos', f"task_{edit_task_id_for_agent}")
        output_dir_full_path = os.path.join(settings.MEDIA_ROOT, output_dir_name)
        os.makedirs(output_dir_full_path, exist_ok=True)
        
        output_filename_base = f"edited_output_{uuid.uuid4().hex[:8]}"
        output_video_relative_path = os.path.join(output_dir_name, f"{output_filename_base}.mp4")
        output_video_full_path = os.path.join(output_dir_full_path, f"{output_filename_base}.mp4")

        temp_clip_for_duration_obj = None # To ensure it's closed
        edited_clip_obj = None # To ensure it's closed

        try:
            temp_clip_for_duration_obj = VideoFileClip(input_video_path)
            video_duration = temp_clip_for_duration_obj.duration
            temp_clip_for_duration_obj.close() # Close immediately after getting duration

            edit_commands = self._interpret_prompt(prompt, video_duration)
            if not edit_commands or edit_commands[0].get('action') == 'no_op':
                error_msg = edit_commands[0]['params'].get('reason', 'Could not understand editing prompt.')
                logger.warning(f"EditorAgent Task {edit_task_id_for_agent}: {error_msg}")
                return {"status": "failed", "error": error_msg}

            # Basic safeguard for problematic keywords (very simple)
            problematic_keywords = ["some_very_bad_keyword", "another_inappropriate_term"] # Example list
            if any(keyword in prompt.lower() for keyword in problematic_keywords):
                logger.warning(f"EditorAgent Task {edit_task_id_for_agent}: Prompt contains potentially problematic keywords. Rejecting edit.")
                return {"status": "failed", "error": "Edit rejected due to problematic content in prompt."}


            logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Interpreted commands: {edit_commands}")
            
            edited_clip_obj = self._apply_edit_commands(input_video_path, edit_commands)

            if edited_clip_obj:
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits successful. Writing output to {output_video_full_path}")
                edited_clip_obj.write_videofile(
                    output_video_full_path, 
                    codec='libx264', audio_codec='aac',
                    temp_audiofile=os.path.join(output_dir_full_path, f"{output_filename_base}_temp_audio.m4a"),
                    remove_temp=True, threads=settings.MOVIEPY_THREADS if hasattr(settings, 'MOVIEPY_THREADS') else 4, # Use from settings if available
                    preset=settings.MOVIEPY_PRESET if hasattr(settings, 'MOVIEPY_PRESET') else 'medium', # Use from settings
                    logger='bar'
                )
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Video successfully edited and saved to {output_video_relative_path}")
                
                return {
                    "status": "completed",
                    "output_media_path": output_video_relative_path, 
                    "output_preview_url": None 
                }
            else:
                logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits resulted in no video clip.")
                return {"status": "failed", "error": "Editing process failed to produce a video."}

        except Exception as e:
            logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Critical error during video editing: {e}", exc_info=True)
            return {"status": "failed", "error": f"An unexpected error occurred during video editing: {str(e)}"}
        finally:
            if temp_clip_for_duration_obj: temp_clip_for_duration_obj.close()
            if edited_clip_obj: edited_clip_obj.close()

            if temp_download_dir_for_cleanup and os.path.exists(temp_download_dir_for_cleanup):
                try:
                    shutil.rmtree(temp_download_dir_for_cleanup)
                    logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Cleaned up temporary download directory: {temp_download_dir_for_cleanup}")
                except Exception as e_clean:
                    logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Error cleaning up temp download dir {temp_download_dir_for_cleanup}: {e_clean}", exc_info=True)
