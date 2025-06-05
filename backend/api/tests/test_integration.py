# backend/api/tests/test_integration.py
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase, APIClient # Use APIClient for DRF views
from unittest.mock import patch
import uuid

from api.models import SearchTask

class IntegrationTests(APITestCase): # Inherit from APITestCase for DRF testing
    """Basic integration tests for API workflows."""

    def setUp(self):
        self.user = User.objects.create_user(username='integuser', email='integ@example.com', password='password123')
        self.client = APIClient() # Use APIClient

    @patch('api.tasks.process_search_query_task.delay') # Mock the Celery task
    def test_search_initiation_creates_task(self, mock_process_search_task):
        """
        Test that initiating a search creates a SearchTask and calls the Celery task.
        """
        self.client.force_authenticate(user=self.user)
        url = reverse('api:search_initiate')
        data = {'query_text': 'integration test search'}
        
        response = self.client.post(url, data, format='json') # format='json' for APIClient

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue('id' in response.data)
        
        task_id_str = response.data['id']
        task_id_uuid = uuid.UUID(task_id_str) # Convert string UUID to UUID object

        # Check if SearchTask was created in DB
        self.assertTrue(SearchTask.objects.filter(id=task_id_uuid).exists())
        search_task = SearchTask.objects.get(id=task_id_uuid)
        self.assertEqual(search_task.query_text, 'integration test search')
        self.assertEqual(search_task.user, self.user)
        self.assertEqual(search_task.status, 'pending') # Initial status before Celery task runs

        # Check if Celery task was called with the correct task ID
        mock_process_search_task.assert_called_once_with(task_id_uuid)

    # Add more integration tests:
    # - Full search flow (initiate -> poll status -> get results) but this requires mocking Celery execution and MainOrchestrator
    # - Video editing flow (create project -> create task -> poll status -> get result URL)
