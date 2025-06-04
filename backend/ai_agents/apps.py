# backend/ai_agents/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class AiAgentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_agents'
    verbose_name = "PAPRI AI Agents"

    def ready(self):
        # This method is called when Django starts.
        # You can put initialization code here, e.g., loading models if not done lazily.
        # However, be cautious with heavy initializations here as it can slow down startup.
        # It's often better to load models/resources on first use within the agents themselves.
        logger.info("AI Agents App (Papri) is ready.")
        # Example:
        # from .some_heavy_model_loader import load_all_ai_models
        # load_all_ai_models() # Call this only if truly necessary at startup
