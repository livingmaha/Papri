# backend/api/analyzer_instances.py
import logging
from typing import Optional

# Import the analyzer classes from their correct location in the ai_agents package
# These imports assume your project structure places ai_agents at the same level as the api app,
# both typically within a 'backend' directory.
from backend.ai_agents.visual_analyzer import VisualAnalyzer
from backend.ai_agents.transcript_analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)

# --- Global Analyzer Instances ---
# These will be populated by the initialize_analyzers function.
visual_analyzer_instance: Optional[VisualAnalyzer] = None
transcript_analyzer_instance: Optional[TranscriptAnalyzer] = None

# Flag to ensure initialization logic runs only once.
_analyzers_initialized = False

def initialize_analyzers():
    """
    Initializes the global singleton instances of VisualAnalyzer and TranscriptAnalyzer.
    This function is designed to be idempotent (safe to call multiple times,
    but will only perform initialization once).
    It's recommended to call this from an AppConfig.ready() method in one of your
    Django apps (e.g., api.apps.ApiConfig or ai_agents.apps.AiAgentsConfig)
    to ensure it runs when Django is fully initialized.
    """
    global visual_analyzer_instance, transcript_analyzer_instance, _analyzers_initialized
    
    if _analyzers_initialized:
        logger.debug("Global analyzers (visual_analyzer_instance, transcript_analyzer_instance) already initialized. Skipping re-initialization.")
        return

    logger.info("Attempting to initialize global analyzer instances (VisualAnalyzer, TranscriptAnalyzer)...")

    try:
        logger.info("Initializing global VisualAnalyzer instance...")
        visual_analyzer_instance = VisualAnalyzer() # This instantiation might load heavy ML models.
        logger.info("Global VisualAnalyzer instance initialized successfully.")
    except Exception as e:
        visual_analyzer_instance = None # Ensure it's None on failure
        logger.critical(f"CRITICAL FAILURE: Could not initialize global VisualAnalyzer instance: {e}", exc_info=True)
        # Depending on requirements, you might re-raise this error to halt startup
        # or allow the application to run with this service degraded.

    try:
        logger.info("Initializing global TranscriptAnalyzer instance...")
        transcript_analyzer_instance = TranscriptAnalyzer() # This also might load models.
        logger.info("Global TranscriptAnalyzer instance initialized successfully.")
    except Exception as e:
        transcript_analyzer_instance = None # Ensure it's None on failure
        logger.critical(f"CRITICAL FAILURE: Could not initialize global TranscriptAnalyzer instance: {e}", exc_info=True)

    _analyzers_initialized = True
    logger.info("Global analyzer instances initialization process has concluded.")

# --- Automatic Initialization Attempt on Module Import (Common Pattern) ---
# This block ensures that if this module is imported, an attempt to initialize
# the analyzers is made. The _analyzers_initialized flag prevents redundant calls.
# For Django projects, explicitly calling initialize_analyzers() from an AppConfig.ready()
# method provides more deterministic control over the startup sequence.

if not _analyzers_initialized:
    initialize_analyzers()

# --- Getter Functions for Controlled Access ---
def get_visual_analyzer() -> Optional[VisualAnalyzer]:
    """
    Provides access to the globally initialized VisualAnalyzer instance.
    Returns the instance or None if it failed to initialize.
    """
    if not _analyzers_initialized:
        # This might indicate that initialize_analyzers() hasn't been called yet or is in progress.
        # Depending on Django's import order, this warning might appear during startup.
        # It's generally safer if dependent modules call this after AppConfig.ready().
        logger.debug("get_visual_analyzer() called, but global initialization may not have completed. Attempting direct init check.")
        # In case it wasn't called via module import and AppConfig hasn't run yet.
        # This is a fallback, primary init should be from AppConfig or module load.
        initialize_analyzers() 

    if not visual_analyzer_instance:
        logger.warning("VisualAnalyzer instance is not available. It may have failed to initialize or is being accessed before successful initialization.")
    return visual_analyzer_instance

def get_transcript_analyzer() -> Optional[TranscriptAnalyzer]:
    """
    Provides access to the globally initialized TranscriptAnalyzer instance.
    Returns the instance or None if it failed to initialize.
    """
    if not _analyzers_initialized:
        logger.debug("get_transcript_analyzer() called, but global initialization may not have completed. Attempting direct init check.")
        initialize_analyzers()

    if not transcript_analyzer_instance:
        logger.warning("TranscriptAnalyzer instance is not available. It may have failed to initialize or is being accessed before successful initialization.")
    return transcript_analyzer_instance
