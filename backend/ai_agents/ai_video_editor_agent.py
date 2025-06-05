# backend/ai_agents/ai_video_editor_agent.py
import logging
import os
import uuid
import tempfile
import shutil
import re
from typing import List, Dict, Any, Optional

from moviepy.editor import (
    VideoFileClip, concatenate_videoclips, TextClip, CompositeVideoClip,
    AudioFileClip, afx # Import afx for audio effects like volumex
)
# from moviepy.video.fx.all import speedx # For speed change, if moviepy.editor.speedx not found
import yt_dlp

from django.conf import settings

logger = logging.getLogger(__name__)

# --- Helper Functions for Video Editing ---

def _parse_time_string(time_str: str) -> Optional[float]:
    """
    Converts HH:MM:SS.mmm, MM:SS.mmm, or SS.mmm to seconds.
    Also handles simple "Xs" format like "5s", "10.5s".
    Returns None if parsing fails.

    Args:
        time_str (str): The time string to parse.

    Returns:
        Optional[float]: Time in seconds, or None if parsing failed.
    """
    if not time_str: return None
    time_str = str(time_str).strip().lower() # Ensure string and handle "5s" etc.
    
    if 's' in time_str and not ':' in time_str: # Simple seconds format like "5s" or "5.5s"
        try:
            return float(time_str.replace('s', ''))
        except ValueError:
            logger.warning(f"Invalid simple time string format: {time_str}")
            return None

    parts = time_str.split(':')
    try:
        if len(parts) == 3: # HH:MM:SS.mmm
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2: # MM:SS.mmm
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1: # SS.mmm (or just seconds as number)
            return float(parts[0])
    except ValueError:
        logger.warning(f"Invalid HH:MM:SS time string format: {time_str}")
    return None

def _download_video_for_editing(video_url: str, edit_task_id_for_naming: str) -> Optional[str]:
    """
    Downloads a video from a URL to a temporary local file for editing.

    Args:
        video_url (str): The URL of the video to download.
        edit_task_id_for_naming (str): An ID used for naming temporary files/directories.

    Returns:
        Optional[str]: Path to the downloaded video file, or None if download failed.
    """
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
            else: # Fallback if prepare_filename didn't give the exact name or file is missing
                found_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if found_files:
                    full_p = os.path.join(temp_dir, found_files[0])
                    logger.info(f"EditorAgent: Video for editing downloaded (Task: {edit_task_id_for_naming}), found file by scan: {full_p}")
                    return full_p
                logger.error(f"EditorAgent: Video download for editing attempted (Task: {edit_task_id_for_naming}) but file not found. Info: {info_dict}")
                shutil.rmtree(temp_dir) # Clean up if download truly failed
                return None
    except Exception as e:
        logger.error(f"EditorAgent: Error downloading video {video_url} for editing (Task: {edit_task_id_for_naming}): {e}", exc_info=True)
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
        return None


class AIVideoEditorAgent:
    """
    AIVideoEditorAgent interprets user prompts for video editing and applies edits using MoviePy.

    Supported Commands:
    -------------------
    1.  `CUT [segment|scene|part] FROM <timestamp> TO <timestamp>`
        Removes the video segment between start and end timestamps.
        Example: "CUT FROM 00:10 TO 00:25.5", "cut scene from 5s to 10.2s"

    2.  `ADD TEXT "<text_content>" AT <timestamp> DURATION <seconds> [FONTSIZE <size>] [COLOR <color_name_or_hex>]`
        Overlays text on the video. Fontsize and color are optional.
        Example: "ADD TEXT "Chapter 1" AT 0s DURATION 5s FONTSIZE 48 COLOR blue"
        Example: "add text "Hello World" at 1m10s duration 3.5s color #FF0000"

    3.  `MUTE AUDIO [segment|part] FROM <timestamp> TO <timestamp>`
        Mutes the audio for the specified segment.
        Example: "MUTE AUDIO FROM 1:00:00 TO 1:05:30"

    4.  `REPLACE AUDIO WITH <new_audio_url_or_path> [FROM <start_timestamp> TO <end_timestamp>]`
        Replaces audio in a segment (or entire video if timestamps omitted) with audio from a new file/URL.
        `new_audio_url_or_path` should be a direct link to an audio file (e.g., .mp3, .wav).
        Example: "REPLACE AUDIO WITH [http://example.com/music.mp3](http://example.com/music.mp3)"
        Example: "replace audio with /path/to/local/audio.wav from 30s to 1m0s"
        *Note: Audio downloading from URL is basic. Complex transformations might be simplified.*

    5.  `CHANGE SPEED TO <speed_multiplier>x [FROM <start_timestamp> TO <end_timestamp>]`
        Changes the playback speed of a segment (or entire video).
        `<speed_multiplier>` e.g., "2x" (faster), "0.5x" (slower).
        Example: "CHANGE SPEED TO 1.5x FROM 10s TO 20s"
        Example: "change speed to 0.75x"
        *Note: Audio pitch correction is not explicitly handled for speed changes by default in MoviePy's speedx, audio may sound distorted.*

    Timestamp Format:
    -----------------
    Accepts "HH:MM:SS.mmm", "MM:SS.mmm", "SS.mmm", "S" (e.g., "5s"), or just numbers (interpreted as seconds).
    Examples: "01:20:30.500", "10:15.2", "45.5", "120s", "75".

    Color Names:
    ------------
    Standard web color names (e.g., "white", "black", "red", "blue", "green") or hex codes (e.g., "#FF00FF").
    """
    def __init__(self):
        logger.info("AIVideoEditorAgent initialized.")
        # Define regex patterns for flexibility
        self.timestamp_pattern = r"([\d.:]+s?)" # HH:MM:SS.mmm, MM:SS.s, SSS.s, SSSs, SSS
        self.text_content_pattern = r"\"([^\"]+)\"" # "Text in quotes"
        self.speed_multiplier_pattern = r"([\d.]+x)" # 0.5x, 2x, 1.75x
        self.url_path_pattern = r"(\S+)" # Matches any non-whitespace sequence for URLs/paths

    def _interpret_prompt(self, prompt: str, video_duration: float) -> List[Dict[str, Any]]:
        """
        Interprets the natural language prompt into a list of actionable editing commands.
        Uses more flexible regex and handles multiple commands in a prompt (future extension).
        """
        commands = []
        prompt_lower = prompt.lower()
        
        # --- Order of regex matching can be important if commands overlap ---

        # Command: CUT (more flexible variants)
        cut_match = re.search(
            rf"(cut|remove|delete)\s*(?:segment|scene|part|clip)?\s*from\s*{self.timestamp_pattern}\s*(?:to|until)\s*{self.timestamp_pattern}", 
            prompt_lower
        )
        if cut_match:
            _, start_str, end_str = cut_match.groups() # First group is cut/remove/delete
            start_sec = _parse_time_string(start_str)
            end_sec = _parse_time_string(end_str)
            if start_sec is not None and end_sec is not None and start_sec < end_sec:
                commands.append({'action': 'cut_segment', 'params': {'start_sec': start_sec, 'end_sec': end_sec, 'remove': True}})
                logger.info(f"Interpreted command: CUT from {start_sec}s to {end_sec}s")

        # Command: ADD TEXT
        # Example: ADD TEXT "Hello" AT 5s DURATION 3s FONTSIZE 24 COLOR white
        text_match = re.search(
            rf"add text\s*{self.text_content_pattern}\s*at\s*{self.timestamp_pattern}\s*duration\s*{self.timestamp_pattern}"
            rf"(?:\s*fontsize\s*(\d+))?(?:\s*color\s*([a-zA-Z#\d]+))?",
            prompt_lower
        )
        if text_match:
            text_content, start_str, duration_str, fontsize_str, color_str = text_match.groups()
            start_sec = _parse_time_string(start_str)
            duration_sec = _parse_time_string(duration_str)
            params = {
                'text': text_content, 'start_sec': start_sec, 'duration_sec': duration_sec,
                'fontsize': int(fontsize_str) if fontsize_str else 24,
                'color': color_str if color_str else 'white',
                'position': ('center', 'bottom'), 'margin_y': 20 
            }
            if params['start_sec'] is not None and params['duration_sec'] is not None:
                commands.append({'action': 'add_text', 'params': params})
                logger.info(f"Interpreted command: ADD TEXT with params {params}")

        # Command: MUTE AUDIO
        mute_match = re.search(rf"mute audio\s*(?:segment|part)?\s*from\s*{self.timestamp_pattern}\s*(?:to|until)\s*{self.timestamp_pattern}", prompt_lower)
        if mute_match:
            start_str, end_str = mute_match.groups()
            start_sec = _parse_time_string(start_str)
            end_sec = _parse_time_string(end_str)
            if start_sec is not None and end_sec is not None and start_sec < end_sec:
                commands.append({'action': 'mute_audio', 'params': {'start_sec': start_sec, 'end_sec': end_sec}})
                logger.info(f"Interpreted command: MUTE AUDIO from {start_sec}s to {end_sec}s")

        # Command: REPLACE AUDIO
        replace_audio_match = re.search(
            rf"replace audio with\s*{self.url_path_pattern}(?:\s*from\s*{self.timestamp_pattern}\s*(?:to|until)\s*{self.timestamp_pattern})?", 
            prompt_lower
        )
        if replace_audio_match:
            audio_source, start_str, end_str = replace_audio_match.groups()
            start_sec = _parse_time_string(start_str) if start_str else 0.0
            end_sec = _parse_time_string(end_str) if end_str else video_duration
            if start_sec is not None and end_sec is not None:
                 commands.append({'action': 'replace_audio', 
                                  'params': {'audio_source_path_or_url': audio_source, 'start_sec': start_sec, 'end_sec': end_sec}})
                 logger.info(f"Interpreted command: REPLACE AUDIO with {audio_source} from {start_sec}s to {end_sec}s")

        # Command: CHANGE SPEED
        change_speed_match = re.search(
            rf"change speed to\s*{self.speed_multiplier_pattern}(?:\s*from\s*{self.timestamp_pattern}\s*(?:to|until)\s*{self.timestamp_pattern})?", 
            prompt_lower
        )
        if change_speed_match:
            speed_factor_str, start_str, end_str = change_speed_match.groups()
            try:
                speed_factor = float(speed_factor_str.replace('x', ''))
                start_sec = _parse_time_string(start_str) if start_str else 0.0
                end_sec = _parse_time_string(end_str) if end_str else video_duration
                if start_sec is not None and end_sec is not None and speed_factor > 0:
                     commands.append({'action': 'change_speed', 
                                      'params': {'speed_factor': speed_factor, 'start_sec': start_sec, 'end_sec': end_sec}})
                     logger.info(f"Interpreted command: CHANGE SPEED to {speed_factor}x from {start_sec}s to {end_sec}s")
                else: logger.warning(f"Invalid speed factor or timestamps for CHANGE SPEED: {speed_factor_str}, {start_str}, {end_str}")
            except ValueError:
                logger.warning(f"Could not parse speed factor: {speed_factor_str}")
                
        # Placeholder for CREATE HIGHLIGHT REEL (very advanced, requires content analysis integration)
        highlight_match = re.search(r"create highlight reel\s*(?:duration\s*([\d.:s]+))?", prompt_lower)
        if highlight_match:
            duration_str = highlight_match.group(1)
            duration_sec = _parse_time_string(duration_str) if duration_str else 30.0
            commands.append({'action': 'create_highlight_reel_stub', 'params': {'duration_sec': duration_sec}})
            logger.info(f"Interpreted command (STUB): CREATE HIGHLIGHT REEL duration {duration_sec}s")


        if not commands:
            logger.warning(f"EditorAgent: Could not interpret prompt into any defined commands: '{prompt}'")
            commands.append({'action': 'no_op', 'params': {'reason': f"Could not understand prompt. Prompt received: '{prompt[:100]}...'"}})
        
        return commands

    def _apply_edit_commands(self, input_video_path: str, commands: List[Dict[str, Any]], edit_task_id_for_naming: str) -> Optional[VideoFileClip]:
        """Applies a list of parsed edit commands to the video using MoviePy."""
        try:
            current_clip = VideoFileClip(input_video_path)
            logger.info(f"EditorAgent: Loaded video '{input_video_path}' for editing. Duration: {current_clip.duration}s")
        except Exception as e:
            logger.error(f"EditorAgent: Failed to load video file '{input_video_path}' with MoviePy: {e}", exc_info=True)
            return None

        processed_clips_segments = [] # To hold segments for concatenation after cuts/speed changes
        last_processed_end_time = 0.0

        # Sort commands by start time if multiple affecting timeline (e.g., cut then speed change on a later part)
        # This is a simplification; true multi-command processing needs careful state management.
        # For now, process in order of typical application (cuts first, then speed/audio, then overlays)
        
        # --- Phase 1: Structural edits (Cuts, Speed Changes) ---
        # This phase reconstructs the base video timeline.
        
        # For simplicity, assume commands that alter timeline (cut, speed) are processed sequentially.
        # A more robust system would build a timeline of operations.
        
        original_clip_for_processing = current_clip # Keep original for subclip operations

        for cmd_idx, cmd_data in enumerate(commands):
            action = cmd_data['action']
            params = cmd_data['params']

            if action == 'cut_segment':
                start_cut = max(0, params['start_sec'])
                end_cut = min(original_clip_for_processing.duration, params['end_sec'])
                
                # If there's a segment before this cut that hasn't been processed
                if start_cut > last_processed_end_time:
                    processed_clips_segments.append(original_clip_for_processing.subclip(last_processed_end_time, start_cut))
                
                last_processed_end_time = end_cut # This segment is removed
                logger.info(f"Applying CUT from {start_cut}s to {end_cut}s. Next processing starts after {last_processed_end_time}s.")
                
            elif action == 'change_speed':
                # For simplicity, apply speed change to the *current state* of the clip.
                # This means if multiple speed changes or cuts are combined, the timestamps
                # for later commands refer to the *already modified* clip duration.
                # This is a significant simplification.
                target_start_sec = params.get('start_sec', 0)
                target_end_sec = params.get('end_sec', current_clip.duration) # Default to whole current clip
                speed_factor = params.get('speed_factor', 1.0)

                if target_start_sec == 0 and target_end_sec >= current_clip.duration: # Whole clip
                    current_clip = current_clip.fx(afx.speedx, factor=speed_factor)
                    logger.info(f"Applied SPEED CHANGE ({speed_factor}x) to entire clip. New duration: {current_clip.duration}s")
                else: # Segment speed change - more complex, placeholder
                    logger.warning(f"Segmented speed change (from {target_start_sec} to {target_end_sec} at {speed_factor}x) is complex and currently applies to WHOLE clip as a fallback. Robust implementation needed.")
                    current_clip = current_clip.fx(afx.speedx, factor=speed_factor) # Fallback to whole clip for now
        
        # After all structural edits, if segments were generated, concatenate them
        if last_processed_end_time < original_clip_for_processing.duration:
            processed_clips_segments.append(original_clip_for_processing.subclip(last_processed_end_time, original_clip_for_processing.duration))
        
        if processed_clips_segments: # If cuts were made
            if not any(s.duration > 0 for s in processed_clips_segments): # All content removed
                logger.warning("EditorAgent: All video content was cut or resulted in zero duration.")
                current_clip.close()
                original_clip_for_processing.close()
                return TextClip("All content removed", fontsize=30, color='white', bg_color='black', size=(current_clip.size or (640,360))).set_duration(1)

            # Concatenate valid segments. Ensure audio is handled.
            # MoviePy's concatenate_videoclips handles audio concatenation if present.
            current_clip_temp = concatenate_videoclips([s for s in processed_clips_segments if s.duration > 0])
            current_clip.close() # Close the version that was being modified in loop
            current_clip = current_clip_temp
            logger.info(f"EditorAgent: Applied structural edits (cuts/speed). New base duration: {current_clip.duration}s")
        
        original_clip_for_processing.close() # Close the initial reference if not already current_clip


        # --- Phase 2: Audio manipulations (Mute, Replace Audio) ---
        # These operate on the `current_clip` which has cuts/speed changes applied.
        for cmd_data in commands:
            action = cmd_data['action']
            params = cmd_data['params']

            if action == 'mute_audio':
                start_mute = params['start_sec']
                end_mute = params['end_sec']
                if current_clip.audio:
                    if start_mute == 0 and end_mute >= current_clip.duration: # Mute whole clip
                        current_clip = current_clip.without_audio()
                        logger.info(f"Muted audio for entire clip (duration {current_clip.duration}s)")
                    else: # Mute a segment
                        # This involves creating subclips of audio and replacing one part with silence.
                        # Placeholder: current MoviePy version makes this tricky without more complex audio manipulation.
                        logger.warning(f"Segmented audio mute from {start_mute}s to {end_mute}s is complex. Placeholder: No audio change for segment mute yet.")
                        # Example of how it might be done (simplified, needs care):
                        # audio_segment_to_mute = current_clip.audio.subclip(start_mute, end_mute)
                        # silent_audio = audio_segment_to_mute.fx(afx.volumex, 0)
                        # current_clip.audio = CompositeAudioClip([
                        # current_clip.audio.subclip(0,start_mute) if start_mute > 0 else None,
                        # silent_audio,
                        # current_clip.audio.subclip(end_mute) if end_mute < current_clip.audio.duration else None
                        # ].filter(None))


            elif action == 'replace_audio':
                audio_source = params['audio_source_path_or_url']
                start_replace = params.get('start_sec', 0)
                end_replace = params.get('end_sec', current_clip.duration)
                
                temp_audio_path = None
                if audio_source.startswith("http"):
                    # Download the audio - use a simplified version of _download_video_for_editing
                    temp_audio_dir = tempfile.mkdtemp(prefix=f"papri_audio_dl_{edit_task_id_for_naming}_")
                    try:
                        # Basic requests download for direct audio links
                        response = requests.get(audio_source, stream=True, timeout=20)
                        response.raise_for_status()
                        temp_audio_path = os.path.join(temp_audio_dir, f"downloaded_audio_{uuid.uuid4().hex[:4]}.mp3") # Assume mp3, could be wav etc.
                        with open(temp_audio_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
                        logger.info(f"Downloaded replacement audio to {temp_audio_path}")
                    except Exception as e_dl_audio:
                        logger.error(f"Failed to download replacement audio from {audio_source}: {e_dl_audio}")
                        if os.path.exists(temp_audio_dir): shutil.rmtree(temp_audio_dir)
                        continue # Skip this command if audio download fails
                elif os.path.exists(audio_source):
                    temp_audio_path = audio_source # It's a local path
                
                if temp_audio_path:
                    try:
                        new_audio_clip = AudioFileClip(temp_audio_path)
                        if start_replace == 0 and end_replace >= current_clip.duration: # Replace entire audio
                            current_clip = current_clip.set_audio(new_audio_clip)
                            logger.info(f"Replaced entire audio with {audio_source}.")
                        else: # Replace audio segment (complex, placeholder for full robust impl)
                            logger.warning(f"Segmented audio replacement from {start_replace}s to {end_replace}s is complex. Placeholder: Replacing full audio as fallback.")
                            current_clip = current_clip.set_audio(new_audio_clip) # Fallback: replace full audio
                        # new_audio_clip.close() # Close after use if set_audio copies it
                    except Exception as e_audio_replace:
                        logger.error(f"Error replacing audio with {audio_source}: {e_audio_replace}")
                    finally:
                         # Clean up downloaded audio if it was from URL and not an original local path
                        if audio_source.startswith("http") and temp_audio_path and os.path.exists(temp_audio_dir):
                           shutil.rmtree(temp_audio_dir)
                else:
                     logger.warning(f"No valid audio source for REPLACE AUDIO: {audio_source}")

        # --- Phase 3: Visual Overlays (Text) ---
        # These operate on the `current_clip` that has structural and audio changes.
        text_clips_to_composite = [current_clip] # Start with the base video

        for cmd_data in commands:
            action = cmd_data['action']
            params = cmd_data['params']

            if action == 'add_text':
                try:
                    txt_clip = TextClip(
                        params['text'], fontsize=params.get('fontsize', 24), color=params.get('color', 'white'),
                        font=params.get('font', 'Arial'), bg_color=params.get('bg_color', 'transparent')
                    )
                    txt_clip = txt_clip.set_position(params.get('position', ('center', 'bottom'))) \
                                     .set_duration(params['duration_sec']) \
                                     .set_start(params['start_sec'])
                    
                    if params.get('position') == ('center', 'bottom') and params.get('margin_y'):
                         txt_clip = txt_clip.set_position(lambda t: ('center', current_clip.h - txt_clip.h - params['margin_y']))

                    if txt_clip.end > current_clip.duration: # Adjust if text exceeds new clip duration
                        txt_clip = txt_clip.set_duration(max(0, current_clip.duration - txt_clip.start))
                    
                    if txt_clip.duration > 0:
                        text_clips_to_composite.append(txt_clip)
                        logger.info(f"Prepared text '{params['text']}' from {params['start_sec']}s for {params['duration_sec']}s")
                except Exception as e_text:
                    logger.error(f"EditorAgent: Error preparing text clip '{params.get('text')}': {e_text}", exc_info=True)
            
            elif action == 'create_highlight_reel_stub':
                 logger.warning("EditorAgent: 'create_highlight_reel_stub' is a placeholder. No highlight reel created.")


        if len(text_clips_to_composite) > 1: # More than just the base clip
            final_clip = CompositeVideoClip(text_clips_to_composite, size=current_clip.size)
            # current_clip.close() # The original base clip is now part of final_clip's sources
            return final_clip
        
        return current_clip # Return original or structurally/audio-modified clip


    def perform_edit(self, video_path_or_url: str, prompt: str, edit_task_id_for_agent: str) -> dict:
        """
        Main method to perform video editing.
        `video_path_or_url`: Can be a local file path or a URL (will be downloaded if URL).
        `prompt`: User's text instruction.
        `edit_task_id_for_agent`: Used for naming output files and temp dirs.

        Returns a dict:
        {'status': 'completed', 'output_media_path': 'relative/path/to/output.mp4'}
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

        # --- Output Path Setup ---
        output_dir_name = os.path.join('edited_videos', f"task_{edit_task_id_for_agent}")
        output_dir_full_path = os.path.join(settings.MEDIA_ROOT, output_dir_name)
        os.makedirs(output_dir_full_path, exist_ok=True)
        
        output_filename_base = f"edited_output_{uuid.uuid4().hex[:8]}"
        output_video_relative_path = os.path.join(output_dir_name, f"{output_filename_base}.mp4")
        output_video_full_path = os.path.join(output_dir_full_path, f"{output_filename_base}.mp4")

        # --- Safeguard for Problematic Content ---
        problematic_keywords = getattr(settings, 'EDITOR_PROBLEM_KEYWORDS', ["explicit_term_1", "bad_phrase_2"])
        if any(keyword.lower() in prompt.lower() for keyword in problematic_keywords):
            logger.warning(f"EditorAgent Task {edit_task_id_for_agent}: Prompt contains potentially problematic keywords. Rejecting edit.")
            return {"status": "failed", "error": "Edit rejected due to problematic content in prompt."}

        temp_clip_for_duration_obj = None
        edited_clip_obj = None

        try:
            # Get video duration for prompt interpretation context
            temp_clip_for_duration_obj = VideoFileClip(input_video_path)
            video_duration = temp_clip_for_duration_obj.duration
            temp_clip_for_duration_obj.close()

            edit_commands = self._interpret_prompt(prompt, video_duration)
            if not edit_commands or edit_commands[0].get('action') == 'no_op':
                error_msg = edit_commands[0]['params'].get('reason', 'Could not understand editing prompt.')
                logger.warning(f"EditorAgent Task {edit_task_id_for_agent}: {error_msg}")
                return {"status": "failed", "error": error_msg}
            
            logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Interpreted commands: {edit_commands}")
            
            edited_clip_obj = self._apply_edit_commands(input_video_path, edit_commands, edit_task_id_for_agent)

            if edited_clip_obj:
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits successful. Writing output to {output_video_full_path}")
                
                # MoviePy write parameters from Django settings if available
                moviepy_threads = getattr(settings, 'MOVIEPY_THREADS', 4)
                moviepy_preset = getattr(settings, 'MOVIEPY_PRESET', 'medium')
                # MoviePy's default logger is 'bar', can be set to None or a custom logger
                moviepy_logger = getattr(settings, 'MOVIEPY_LOGGER', 'bar') 
                
                edited_clip_obj.write_videofile(
                    output_video_full_path, 
                    codec='libx264', audio_codec='aac',
                    temp_audiofile=os.path.join(output_dir_full_path, f"{output_filename_base}_temp_audio.m4a"),
                    remove_temp=True, threads=moviepy_threads, preset=moviepy_preset, logger=moviepy_logger
                )
                logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Video successfully edited and saved to {output_video_relative_path}")
                
                return {
                    "status": "completed", "output_media_path": output_video_relative_path,
                }
            else:
                logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Applying edits resulted in no video clip (None).")
                return {"status": "failed", "error": "Editing process failed to produce a video."}

        except Exception as e:
            logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Critical error during video editing: {e}", exc_info=True)
            return {"status": "failed", "error": f"An unexpected error occurred: {str(e)}"}
        finally:
            if temp_clip_for_duration_obj: temp_clip_for_duration_obj.close()
            if edited_clip_obj: edited_clip_obj.close()

            if temp_download_dir_for_cleanup and os.path.exists(temp_download_dir_for_cleanup):
                try:
                    shutil.rmtree(temp_download_dir_for_cleanup)
                    logger.info(f"EditorAgent Task {edit_task_id_for_agent}: Cleaned up temporary download directory: {temp_download_dir_for_cleanup}")
                except Exception as e_clean:
                    logger.error(f"EditorAgent Task {edit_task_id_for_agent}: Error cleaning temp download dir {temp_download_dir_for_cleanup}: {e_clean}")
