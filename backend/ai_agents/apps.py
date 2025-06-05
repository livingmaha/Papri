# backend/ai_agents/apps.py
from django.apps import AppConfig
import logging

# Get a logger specific to this module for better traceability
logger = logging.getLogger(__name__)

class AiAgentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_agents' # This should match the directory name of your app
    verbose_name = "PAPRI AI Agent System" # A descriptive name for the Django admin or logs

    def ready(self):
        """
        This method is called when Django starts and the application registry is fully populated.
        It's a suitable place for application-specific initializations that need to run once.
        """
        logger.info(f"Initializing {self.verbose_name} application...")
        
        # If the ai_agents app had any global resources to initialize (similar to
        # how we discussed initializing analyzers for the 'api' app), this would be
        # a good place to do it. For example:
        #
        # from .some_agent_specific_global_resource import initialize_resource
        # initialize_resource()
        #
        # For now, based on our current design, the agents themselves handle their
        # model loading or use shared instances initialized by the 'api' app's AppConfig.
        # If 'analyzer_instances.py' were moved into 'ai_agents', this ready() method
        # would be the ideal place to call 'initialize_analyzers()'.

        logger.info(f"{self.verbose_name} application is ready.")
