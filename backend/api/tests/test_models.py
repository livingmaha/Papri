# backend/api/tests/test_models.py
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from api.models import (
    Video, VideoSource, SearchTask, EditTask, UserProfile, 
    VideoEditProject, SignupCode
)
import uuid

class ModelTests(TestCase):
    """Test suite for API models."""

    def setUp(self):
        """Set up common test data."""
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.video = Video.objects.create(title="Test Video Title", duration_seconds=120)
        self.video_source = VideoSource.objects.create(
            video=self.video,
            platform_name="youtube",
            platform_video_id="testvid123",
            original_url="[https://www.youtube.com/watch?v=testvid123](https://www.youtube.com/watch?v=testvid123)"
        )

    def test_video_creation(self):
        """Test that a Video object can be created."""
        self.assertEqual(self.video.title, "Test Video Title")
        self.assertTrue(self.video.id is not None)
        self.assertIsNotNone(self.video.created_at)
        self.assertIsNotNone(self.video.updated_at)

    def test_video_source_creation(self):
        """Test that a VideoSource object can be created and linked to a Video."""
        self.assertEqual(self.video_source.video, self.video)
        self.assertEqual(self.video_source.platform_name, "youtube")
        self.assertEqual(self.video_source.processing_status, 'pending') # Default status

    def test_user_profile_creation_signal(self):
        """Test that a UserProfile is created automatically for a new User."""
        self.assertTrue(hasattr(self.user, 'profile'))
        self.assertIsInstance(self.user.profile, UserProfile)
        self.assertEqual(self.user.profile.subscription_plan, 'free_trial') # Default

    def test_search_task_creation(self):
        """Test SearchTask creation with minimal data."""
        task = SearchTask.objects.create(user=self.user, query_text="find cats")
        self.assertIsInstance(task.id, uuid.UUID)
        self.assertEqual(task.user, self.user)
        self.assertEqual(task.status, 'pending')

    def test_video_edit_project_creation(self):
        """Test VideoEditProject creation."""
        project = VideoEditProject.objects.create(user=self.user, project_name="My Test Edit")
        self.assertEqual(project.user, self.user)
        self.assertEqual(project.project_name, "My Test Edit")

    def test_edit_task_creation(self):
        """Test EditTask creation linked to a project."""
        project = VideoEditProject.objects.create(user=self.user, project_name="Project For Task")
        edit_task = EditTask.objects.create(project=project, prompt_text="Cut first 5 seconds.")
        self.assertEqual(edit_task.project, project)
        self.assertEqual(edit_task.status, 'pending')
        self.assertTrue(edit_task.id is not None)

    def test_signup_code_expiry(self):
        """Test SignupCode expiry property."""
        valid_code = SignupCode.objects.create(
            email="valid@example.com", 
            code="VALID123",
            expires_at=timezone.now() + timezone.timedelta(days=1)
        )
        expired_code = SignupCode.objects.create(
            email="expired@example.com", 
            code="EXPIRED123",
            expires_at=timezone.now() - timezone.timedelta(days=1)
        )
        self.assertFalse(valid_code.is_expired)
        self.assertTrue(expired_code.is_expired)

    def test_edit_task_get_result_url(self):
        """Test EditTask's get_result_url method."""
        project = VideoEditProject.objects.create(user=self.user)
        task = EditTask.objects.create(project=project, prompt_text="test")
        
        self.assertIsNone(task.get_result_url()) # No path yet
        
        task.result_media_path = "edited_videos/task_123/output.mp4"
        # Assuming MEDIA_URL is '/media/'
        with self.settings(MEDIA_URL='/media/'):
            self.assertEqual(task.get_result_url(), '/media/edited_videos/task_123/output.mp4')

        task.result_media_path = "[http://cdn.example.com/output.mp4](http://cdn.example.com/output.mp4)"
        self.assertEqual(task.get_result_url(), "[http://cdn.example.com/output.mp4](http://cdn.example.com/output.mp4)")
