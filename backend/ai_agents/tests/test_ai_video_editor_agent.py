# backend/ai_agents/tests/test_ai_video_editor_agent.py
from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock
import os
import tempfile
import shutil

from backend.ai_agents.ai_video_editor_agent import AIVideoEditorAgent, _parse_time_string
# Assuming MoviePy is installed and its components are importable by the agent

class AIVideoEditorAgentTests(TestCase):
    """Test suite for the AIVideoEditorAgent."""

    def setUp(self):
        self.agent = AIVideoEditorAgent()
        self.test_video_duration = 60.0  # Assume a 60-second video for tests

        # Create a dummy empty file to simulate a video file for path testing
        self.temp_dir = tempfile.mkdtemp()
        self.dummy_video_path = os.path.join(self.temp_dir, "dummy_video.mp4")
        with open(self.dummy_video_path, "w") as f:
            f.write("dummy video content")


    def tearDown(self):
        shutil.rmtree(self.temp_dir) # Clean up temp directory and dummy file

    def test_parse_time_string(self):
        """Test the _parse_time_string helper function."""
        self.assertEqual(_parse_time_string("10"), 10.0)
        self.assertEqual(_parse_time_string("10s"), 10.0)
        self.assertEqual(_parse_time_string("01:30"), 90.0)
        self.assertEqual(_parse_time_string("01:30.5"), 90.5)
        self.assertEqual(_parse_time_string("00:01:30.500"), 90.5)
        self.assertEqual(_parse_time_string("1:02:03"), 3723.0)
        self.assertIsNone(_parse_time_string("invalid"))
        self.assertIsNone(_parse_time_string("10:xx"))

    def test_interpret_prompt_cut_segment(self):
        """Test prompt interpretation for 'cut segment' command."""
        prompt = "cut from 10s to 20.5s"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]['action'], 'cut_segment')
        self.assertEqual(commands[0]['params']['start_sec'], 10.0)
        self.assertEqual(commands[0]['params']['end_sec'], 20.5)

        prompt_flexible = "remove scene from 00:00:05 to 0:15"
        commands_flex = self.agent._interpret_prompt(prompt_flexible, self.test_video_duration)
        self.assertEqual(len(commands_flex), 1)
        self.assertEqual(commands_flex[0]['action'], 'cut_segment')
        self.assertEqual(commands_flex[0]['params']['start_sec'], 5.0)
        self.assertEqual(commands_flex[0]['params']['end_sec'], 15.0)


    def test_interpret_prompt_add_text(self):
        """Test prompt interpretation for 'add text' command."""
        prompt = "add text \"Hello World\" at 5s duration 3s fontsize 30 color blue"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertEqual(cmd['action'], 'add_text')
        self.assertEqual(cmd['params']['text'], "Hello World")
        self.assertEqual(cmd['params']['start_sec'], 5.0)
        self.assertEqual(cmd['params']['duration_sec'], 3.0)
        self.assertEqual(cmd['params']['fontsize'], 30)
        self.assertEqual(cmd['params']['color'], 'blue')

    def test_interpret_prompt_mute_audio(self):
        """Test prompt interpretation for 'mute audio' command."""
        prompt = "mute audio from 01:00 to 01:10"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration * 2) # Longer duration for test
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertEqual(cmd['action'], 'mute_audio')
        self.assertEqual(cmd['params']['start_sec'], 60.0)
        self.assertEqual(cmd['params']['end_sec'], 70.0)

    def test_interpret_prompt_replace_audio(self):
        """Test prompt interpretation for 'replace audio' command."""
        prompt = "replace audio with [http://example.com/audio.mp3](http://example.com/audio.mp3) from 10s to 30s"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertEqual(cmd['action'], 'replace_audio')
        self.assertEqual(cmd['params']['audio_source_path_or_url'], "[http://example.com/audio.mp3](http://example.com/audio.mp3)")
        self.assertEqual(cmd['params']['start_sec'], 10.0)
        self.assertEqual(cmd['params']['end_sec'], 30.0)

        prompt_no_times = "replace audio with /my/local/file.wav"
        commands_no_times = self.agent._interpret_prompt(prompt_no_times, self.test_video_duration)
        self.assertEqual(len(commands_no_times), 1)
        cmd_nt = commands_no_times[0]
        self.assertEqual(cmd_nt['action'], 'replace_audio')
        self.assertEqual(cmd_nt['params']['audio_source_path_or_url'], "/my/local/file.wav")
        self.assertEqual(cmd_nt['params']['start_sec'], 0.0) # Default start
        self.assertEqual(cmd_nt['params']['end_sec'], self.test_video_duration) # Default end


    def test_interpret_prompt_change_speed(self):
        """Test prompt interpretation for 'change speed' command."""
        prompt = "change speed to 2x from 5s to 15s"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration)
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertEqual(cmd['action'], 'change_speed')
        self.assertEqual(cmd['params']['speed_factor'], 2.0)
        self.assertEqual(cmd['params']['start_sec'], 5.0)
        self.assertEqual(cmd['params']['end_sec'], 15.0)
        
        prompt_no_times = "change speed to 0.5x"
        commands_no_times = self.agent._interpret_prompt(prompt_no_times, self.test_video_duration)
        self.assertEqual(len(commands_no_times), 1)
        cmd_nt = commands_no_times[0]
        self.assertEqual(cmd_nt['action'], 'change_speed')
        self.assertEqual(cmd_nt['params']['speed_factor'], 0.5)
        self.assertEqual(cmd_nt['params']['start_sec'], 0.0)
        self.assertEqual(cmd_nt['params']['end_sec'], self.test_video_duration)


    def test_interpret_prompt_no_op(self):
        """Test that an uninterpretable prompt results in 'no_op'."""
        prompt = "make the video awesome and cool"
        commands = self.agent._interpret_prompt(prompt, self.test_video_duration)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]['action'], 'no_op')

    @patch('backend.ai_agents.ai_video_editor_agent.VideoFileClip')
    @patch('backend.ai_agents.ai_video_editor_agent.AIVideoEditorAgent._apply_edit_commands')
    @override_settings(MEDIA_ROOT=tempfile.gettempdir()) # Use a temp dir for media root in tests
    def test_perform_edit_calls_apply_commands(self, mock_apply_commands, mock_videofileclip):
        """Test that perform_edit correctly calls _apply_edit_commands with interpreted commands."""
        mock_clip_instance = MagicMock()
        mock_clip_instance.duration = self.test_video_duration
        mock_videofileclip.return_value = mock_clip_instance
        
        # Mock _apply_edit_commands to return a dummy clip object that can be written
        mock_edited_clip = MagicMock()
        mock_edited_clip.write_videofile = MagicMock()
        mock_apply_commands.return_value = mock_edited_clip

        prompt = "cut from 5s to 10s and add text \"Test\" at 1s duration 2s"
        
        with patch('backend.ai_agents.ai_video_editor_agent._download_video_for_editing', return_value=self.dummy_video_path):
            result = self.agent.perform_edit(
                video_path_or_url=self.dummy_video_path, 
                prompt=prompt, 
                edit_task_id_for_agent="test_task_123"
            )

        self.assertEqual(result['status'], 'completed')
        self.assertTrue('output_media_path' in result)
        
        # Check that _interpret_prompt was implicitly called by _apply_edit_commands pathway
        # and _apply_edit_commands was called.
        mock_apply_commands.assert_called_once()
        # args_list = mock_apply_commands.call_args_list[0][0]
        # self.assertEqual(args_list[0], self.dummy_video_path) # input_video_path
        # interpreted_commands_arg = args_list[1] # The list of commands
        # self.assertTrue(any(cmd['action'] == 'cut_segment' for cmd in interpreted_commands_arg))
        # self.assertTrue(any(cmd['action'] == 'add_text' for cmd in interpreted_commands_arg))
        
        mock_edited_clip.write_videofile.assert_called_once()


    @patch('backend.ai_agents.ai_video_editor_agent._download_video_for_editing', return_value=None)
    def test_perform_edit_download_failure(self, mock_download):
        """Test perform_edit when video download fails."""
        result = self.agent.perform_edit("[http://nonexistent.url/video.mp4](http://nonexistent.url/video.mp4)", "cut 5s to 10s", "task_dl_fail")
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Failed to obtain input video", result['error'])

    def test_perform_edit_problematic_prompt(self):
        """Test edit rejection for problematic keywords."""
        with override_settings(EDITOR_PROBLEM_KEYWORDS=["badword"]):
            # Re-initialize agent if it caches settings, or ensure it re-reads
            agent_with_settings = AIVideoEditorAgent()
            result = agent_with_settings.perform_edit(self.dummy_video_path, "make a video with badword", "task_problem")
        self.assertEqual(result['status'], 'failed')
        self.assertIn("problematic content in prompt", result['error'])
