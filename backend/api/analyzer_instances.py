# backend/api/analyzer_instances.py
import logging
from django.conf import settings # Ensure Django settings are configured before this runs

# Import the analyzer classes from their correct location in the ai_agents package
from backend.ai_agents.visual_analyzer import VisualAnalyzer
from backend.ai_agents.transcript_analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)

# --- Global Analyzer Instances ---
# These instances will be initialized when this module is first imported.
# Django typically imports modules as part of its startup process.

visual_analyzer_instance: Optional[VisualAnalyzer] = None
transcript_analyzer_instance: Optional[TranscriptAnalyzer] = None

# Flag to ensure initialization happens only once
_analyzers_initialized = False

def initialize_analyzers():
    """
    Initializes the global analyzer instances.
    This function can be called explicitly, e.g., in an AppConfig.ready() method,
    or will be triggered on first import of this module's instances.
    """
    global visual_analyzer_instance, transcript_analyzer_instance, _analyzers_initialized
    
    if _analyzers_initialized:
        logger.debug("Analyzers already initialized.")
        return

    logger.info("Attempting to initialize global analyzer instances...")

    try:
        logger.info("Initializing VisualAnalyzer instance globally...")
        visual_analyzer_instance = VisualAnalyzer()
        logger.info("Global VisualAnalyzer instance initialized successfully.")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to initialize global VisualAnalyzer instance: {e}", exc_info=True)
        # visual_analyzer_instance remains None

    try:
        logger.info("Initializing TranscriptAnalyzer instance globally...")
        transcript_analyzer_instance = TranscriptAnalyzer()
        logger.info("Global TranscriptAnalyzer instance initialized successfully.")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to initialize global TranscriptAnalyzer instance: {e}", exc_info=True)
        # transcript_analyzer_instance remains None

    _analyzers_initialized = True
    logger.info("Global analyzer initialization process complete.")

# --- Ensure initialization on module load ---
# This ensures that if another part of the code imports these instances,
# they attempt to initialize. However, for Django apps, calling this from
# AppConfig.ready() is often preferred for more controlled startup.
# For simplicity and directness matching your original file, we can call it here.
# If this module is imported multiple times, the `_analyzers_initialized` flag prevents re-runs.

if not _analyzers_initialized:
    initialize_analyzers()

# --- Getter functions (optional, provides a check) ---
def get_visual_analyzer() -> Optional[VisualAnalyzer]:
    if not visual_analyzer_instance:
        logger.warning("VisualAnalyzer instance was not initialized successfully or is requested too early.")
    return visual_analyzer_instance

def get_transcript_analyzer() -> Optional[TranscriptAnalyzer]:
    if not transcript_analyzer_instance:
        logger.warning("TranscriptAnalyzer instance was not initialized successfully or is requested too early.")
    return transcript_analyzer_instance
