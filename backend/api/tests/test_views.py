# backend/api/tests/test_views.py
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from unittest.mock import patch, MagicMock
import uuid

from api.models import SearchTask, VideoEditProject, EditTask, UserProfile
# Assuming tasks.py process_search_query_task and process_video_edit_task are Celery tasks

class ViewTests(APITestCase):
    """Test suite for API views."""

    def setUp(self):
        """Set up common test data and client."""
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.client = APIClient()
        # UserProfile should be created by signal

    def test_auth_status_unauthenticated(self):
        """Test auth_status view for unauthenticated user."""
        response = self.client.get(reverse('api:auth_status'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['isAuthenticated'])

    def test_auth_status_authenticated(self):
        """Test auth_status view for authenticated user."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('api:auth_status'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['isAuthenticated'])
        self.assertEqual(response.data['user']['email'], self.user.email)

    @patch('api.tasks.process_search_query_task.delay')
    def test_initiate_search_view_text_query(self, mock_process_search_task):
        """Test initiating a search with a text query."""
        self.client.force_authenticate(user=self.user)
        url = reverse('api:search_initiate')
        data = {'query_text': 'search for cats'}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue('id' in response.data)
        search_task_id = response.data['id']
        self.assertTrue(SearchTask.objects.filter(id=search_task_id, user=self.user).exists())
        mock_process_search_task.assert_called_once_with(uuid.UUID(search_task_id))

    def test_initiate_search_no_query(self):
        """Test initiating search with no query parameters."""
        self.client.force_authenticate(user=self.user)
        url = reverse('api:search_initiate')
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_status_view(self):
        """Test retrieving search task status."""
        task = SearchTask.objects.create(user=self.user, query_text="test status", status="processing")
        url = reverse('api:search_status', kwargs={'task_id': task.id})
        self.client.force_authenticate(user=self.user) # Assuming user needs to be auth'd, or check permissions
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(task.id))
        self.assertEqual(response.data['status'], 'processing')

    def test_search_results_view_processing(self):
        """Test search results view when task is still processing."""
        task = SearchTask.objects.create(user=self.user, query_text="test results", status="processing_sources")
        url = reverse('api:search_results', kwargs={'task_id': task.id})
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED) # 202 if still processing
        self.assertEqual(response.data['task_status'], 'processing_sources')

    # TODO: Add test for search_results view with actual completed results (needs more setup)
    
    def test_create_video_edit_project(self):
        """Test creating a new video edit project."""
        self.client.force_authenticate(user=self.user)
        url = reverse('api:video_edit_project_list_create')
        data = {'project_name': 'My Awesome Edit'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['project_name'], 'My Awesome Edit')
        self.assertTrue(VideoEditProject.objects.filter(user=self.user, project_name='My Awesome Edit').exists())

    @patch('api.tasks.process_video_edit_task.delay')
    def test_create_edit_task_for_project(self, mock_process_edit_task):
        """Test creating an edit task under a project."""
        self.client.force_authenticate(user=self.user)
        project = VideoEditProject.objects.create(user=self.user, project_name="Project For Task", uploaded_video_path="dummy/path.mp4")
        
        url = reverse('api:edit_task_list_create', kwargs={'project_id': project.id})
        data = {'prompt_text': 'Make this video amazing!'}
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue('id' in response.data)
        edit_task_id = response.data['id']
        self.assertTrue(EditTask.objects.filter(id=edit_task_id, project=project).exists())
        mock_process_edit_task.assert_called_once_with(uuid.UUID(edit_task_id))

    def test_edit_task_status_view(self):
        """Test retrieving an edit task's status."""
        project = VideoEditProject.objects.create(user=self.user, project_name="Status Test Project")
        edit_task = EditTask.objects.create(project=project, prompt_text="Check status", status="queued")
        
        url = reverse('api:edit_task_status', kwargs={'id': edit_task.id})
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(edit_task.id))
        self.assertEqual(response.data['status'], 'queued')

    @patch('payments.services.PaystackService.verify_webhook_signature', return_value=True)
    @patch('payments.services.PaystackService.handle_webhook_event')
    def test_paystack_webhook_view_valid_event(self, mock_handle_event, mock_verify_sig):
        """Test PaystackWebhookView with a valid event."""
        mock_handle_event.return_value = (True, "Event processed successfully")
        url = reverse('payments:paystack_webhook') # Assuming 'payments' is the app_name for payments app URLs
        
        payload = {"event": "charge.success", "data": {"reference": "test_ref123", "status": "success", "customer": {"email": "customer@example.com"}}}
        
        response = self.client.post(url, payload, format='json', HTTP_X_PAYSTACK_SIGNATURE="valid_signature")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_verify_sig.assert_called_once()
        mock_handle_event.assert_called_once_with("charge.success", payload['data'])

    @patch('payments.services.PaystackService.verify_webhook_signature', return_value=False)
    def test_paystack_webhook_view_invalid_signature(self, mock_verify_sig):
        """Test PaystackWebhookView with an invalid signature."""
        url = reverse('payments:paystack_webhook')
        payload = {"event": "charge.success", "data": {}}
        
        response = self.client.post(url, payload, format='json', HTTP_X_PAYSTACK_SIGNATURE="invalid_signature")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN) # Forbidden due to signature
        mock_verify_sig.assert_called_once()
