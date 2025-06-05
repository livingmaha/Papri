# backend/ai_agents/tests/test_main_orchestrator.py
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
import uuid

from backend.ai_agents.main_orchestrator import PapriAIAgentOrchestrator
from api.models import SearchTask, Video, VideoSource

class MainOrchestratorTests(TestCase):
    """Test suite for the PapriAIAgentOrchestrator."""

    def setUp(self):
        self.user = User.objects.create_user(username='orch_user', email='orch@example.com', password='password123')
        self.search_task = SearchTask.objects.create(
            id=uuid.uuid4(), # Ensure it has an ID
            user=self.user, 
            query_text="test query for orchestrator"
        )
        self.orchestrator = PapriAIAgentOrchestrator(papri_search_task_id=str(self.search_task.id))

    @patch('backend.ai_agents.query_understanding_agent.QueryUnderstandingAgent.process_text_query')
    @patch('backend.ai_agents.source_orchestration_agent.SourceOrchestrationAgent.fetch_content_from_sources')
    @patch('backend.ai_agents.content_analysis_agent.ContentAnalysisAgent.analyze_video_content')
    @patch('backend.ai_agents.result_aggregation_agent.ResultAggregationAgent.aggregate_and_rank_results')
    def test_execute_search_successful_flow(
        self, mock_aggregate_rank, mock_analyze_content, 
        mock_fetch_sources, mock_process_query
    ):
        """Test a successful search execution flow with mocks for sub-agents."""
        
        # Mock return values for each agent
        mock_process_query.return_value = {
            "original_query_text": "test query", "keywords": ["test", "query"],
            "intent": "general_video_search", "text_embedding": [0.1, 0.2], "query_type": "text"
        }
        mock_fetch_sources.return_value = [
            {"title": "Fetched Video 1", "original_url": "youtube.com1", "platform_name": "youtube", 
             "platform_video_id": "vid1", "duration_seconds": 100, "scraped_at_iso": "2023-01-01T00:00:00Z"}
        ]
        # Mock analyze_video_content to simulate successful analysis
        mock_analyze_content.return_value = {"status": "analysis_complete", "errors": []}
        
        # Mock aggregate_and_rank_results
        mock_aggregate_rank.return_value = [
            {"video_id": "some_video_db_id_1", "combined_score": 0.8, "match_types": ["transcript_semantic"], 
             "best_source": {"platform_name": "youtube", "original_url": "youtube.com1"}}
        ]

        # Simulate a Video and VideoSource for _persist_raw_video_item
        # This part is a bit tricky as _persist_raw_video_item does DB operations.
        # For a pure orchestrator logic test, we might even mock _persist_raw_video_item if it's too complex.
        # Here, we'll let it run but ensure it doesn't break the mocked flow.
        
        search_params = {'query_text': 'test query for orchestrator'}
        result = self.orchestrator.execute_search(search_params)

        self.assertNotIn("error", result)
        self.assertEqual(result.get("search_status_overall"), "completed")
        self.assertEqual(result.get("items_fetched_from_sources"), 1)
        self.assertEqual(result.get("ranked_video_count"), 1)
        
        mock_process_query.assert_called_once()
        mock_fetch_sources.assert_called_once()
        # analyze_video_content might be called if fetch_sources returns items
        if mock_fetch_sources.return_value:
            mock_analyze_content.assert_called() 
        mock_aggregate_rank.assert_called_once()

        # Check SearchTask status was updated
        self.search_task.refresh_from_db()
        self.assertEqual(self.search_task.status, 'completed')


    @patch('backend.ai_agents.query_understanding_agent.QueryUnderstandingAgent.process_text_query')
    def test_execute_search_query_understanding_failure(self, mock_process_query):
        """Test search execution when QueryUnderstandingAgent fails."""
        mock_process_query.return_value = {"error": "Failed to understand query"}
        
        search_params = {'query_text': 'bad query'}
        result = self.orchestrator.execute_search(search_params)
        
        self.assertIn("error", result)
        self.assertEqual(result.get("search_status_overall"), "failed_query_understanding")
        
        self.search_task.refresh_from_db()
        self.assertEqual(self.search_task.status, 'failed_query_understanding')
        self.assertIn("Failed to understand query", self.search_task.error_message)

    # Add more tests for other failure scenarios (SOIAgent fails, CAAgent fails, RARAgent fails)
    # and for different query types (image, hybrid, video_url).
