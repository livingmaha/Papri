# backend/api/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__) # Use a logger specific to this module

class ApiConfig(AppConfig):
    """
    Application configuration for the 'api' app.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api' # This must match the directory name of your app
    verbose_name = "Papri API" # A human-readable name for the admin panel

    def ready(self):
        """
        This method is called when Django starts and the application registry is fully populated.
        It's a good place for application-specific initializations.
        """
        logger.info(f"Initializing {self.verbose_name} application...")

        # Initialize shared analyzer instances here to ensure models are loaded once at startup.
        try:
            # Import locally within ready() to avoid potential AppRegistryNotReady errors
            # or circular imports if analyzer_instances.py itself tries to import Django models
            # at its module level before apps are fully loaded.
            from .analyzer_instances import initialize_analyzers, get_visual_analyzer, get_transcript_analyzer
            
            logger.info(f"{self.verbose_name}: Calling initialize_analyzers()...")
            initialize_analyzers() # This function is idempotent

            # Optional: Verify that instances are available after initialization attempt
            va = get_visual_analyzer()
            ta = get_transcript_analyzer()

            if va:
                logger.info(f"{self.verbose_name}: Global VisualAnalyzer instance confirmed available.")
            else:
                logger.critical(f"{self.verbose_name}: Global VisualAnalyzer instance is NOT available after ready() initialization. Visual analysis features will be impacted.")

            if ta:
                logger.info(f"{self.verbose_name}: Global TranscriptAnalyzer instance confirmed available.")
            else:
                logger.critical(f"{self.verbose_name}: Global TranscriptAnalyzer instance is NOT available after ready() initialization. Transcript analysis features will be impacted.")

            logger.info(f"{self.verbose_name} application ready and shared analyzers initialized (or attempted).")

        except ImportError as e:
            # This can happen if analyzer_instances.py has issues or structure changes.
            logger.error(f"{self.verbose_name}: Could not import 'initialize_analyzers' from .analyzer_instances: {e}. Shared analyzers might not be initialized. Check module paths and dependencies.")
        except Exception as e_init:
            # Catch any other unexpected errors during the initialization call.
            logger.critical(f"{self.verbose_name}: CRITICAL error occurred during initialize_analyzers() call from AppConfig.ready(): {e_init}", exc_info=True)

        # You can connect signals here if your app uses them:
        # from . import signals # Example: if you have a signals.py
        # logger.debug(f"{self.verbose_name}: Signals connected (if any).")
