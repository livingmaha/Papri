# backend/api/analyzer_instances.py
import logging
from typing import Optional
from threading import Lock

# Import the analyzer classes from their correct location in the ai_agents package
from backend.ai_agents.visual_analyzer import VisualAnalyzer
from backend.ai_agents.transcript_analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)

# --- Global Singleton Analyzer Instances ---
# These will hold the single instances of our analyzers.
_visual_analyzer_instance: Optional[VisualAnalyzer] = None
_transcript_analyzer_instance: Optional[TranscriptAnalyzer] = None

# Threading locks to ensure thread-safe initialization if accessed concurrently
# during Django startup or first use (though AppConfig.ready() is preferred for startup).
_visual_analyzer_lock = Lock()
_transcript_analyzer_lock = Lock()

_analyzers_initialized_flag = False # Overall flag

def initialize_analyzers(force_reinitialize: bool = False):
    """
    Initializes (or re-initializes if forced) the global singleton instances
    of VisualAnalyzer and TranscriptAnalyzer.
    This function is designed to be idempotent.
    It's best called from an AppConfig.ready() method.
    """
    global _visual_analyzer_instance, _transcript_analyzer_instance, _analyzers_initialized_flag

    if _analyzers_initialized_flag and not force_reinitialize:
        logger.debug("Analyzers already initialized. Skipping re-initialization.")
        return

    logger.info(f"Attempting to initialize global analyzer instances (Force reinitialize: {force_reinitialize})...")

    # Initialize Visual Analyzer
    with _visual_analyzer_lock:
        if _visual_analyzer_instance is None or force_reinitialize:
            logger.info("Initializing global VisualAnalyzer instance...")
            try:
                _visual_analyzer_instance = VisualAnalyzer()
                logger.info("Global VisualAnalyzer instance initialized successfully.")
            except Exception as e:
                _visual_analyzer_instance = None # Ensure it's None on failure
                logger.critical(f"CRITICAL FAILURE: Could not initialize global VisualAnalyzer instance: {e}", exc_info=True)
        else:
            logger.debug("VisualAnalyzer instance already exists (lock check).")

    # Initialize Transcript Analyzer
    with _transcript_analyzer_lock:
        if _transcript_analyzer_instance is None or force_reinitialize:
            logger.info("Initializing global TranscriptAnalyzer instance...")
            try:
                _transcript_analyzer_instance = TranscriptAnalyzer()
                logger.info("Global TranscriptAnalyzer instance initialized successfully.")
            except Exception as e:
                _transcript_analyzer_instance = None # Ensure it's None on failure
                logger.critical(f"CRITICAL FAILURE: Could not initialize global TranscriptAnalyzer instance: {e}", exc_info=True)
        else:
            logger.debug("TranscriptAnalyzer instance already exists (lock check).")

    if not force_reinitialize:
        _analyzers_initialized_flag = True
    
    logger.info("Global analyzer instances initialization process has concluded.")


def get_visual_analyzer() -> Optional[VisualAnalyzer]:
    """
    Provides access to the globally initialized VisualAnalyzer instance.
    If not initialized, it will attempt to initialize it.
    Returns the instance or None if it failed to initialize.
    """
    if _visual_analyzer_instance is None:
        logger.info("VisualAnalyzer instance not yet created. Attempting initialization via get_visual_analyzer().")
        initialize_analyzers() # Ensure it's initialized if accessed before AppConfig.ready() or on demand
    
    if not _visual_analyzer_instance: # Check again after attempt
        logger.error("VisualAnalyzer instance is NOT available. Initialization might have failed.")
    return _visual_analyzer_instance


def get_transcript_analyzer() -> Optional[TranscriptAnalyzer]:
    """
    Provides access to the globally initialized TranscriptAnalyzer instance.
    If not initialized, it will attempt to initialize it.
    Returns the instance or None if it failed to initialize.
    """
    if _transcript_analyzer_instance is None:
        logger.info("TranscriptAnalyzer instance not yet created. Attempting initialization via get_transcript_analyzer().")
        initialize_analyzers()
        
    if not _transcript_analyzer_instance:
        logger.error("TranscriptAnalyzer instance is NOT available. Initialization might have failed.")
    return _transcript_analyzer_instance

# Optional: Call initialize_analyzers() when this module is first imported.
# This is an alternative to calling it explicitly from AppConfig.ready().
# However, AppConfig.ready() is generally preferred for Django apps as it ensures
# the full Django environment is set up.
# if not _analyzers_initialized_flag:
# initialize_analyzers()
