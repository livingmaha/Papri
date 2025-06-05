# backend/ai_agents/__init__.py

# This file signifies that the 'ai_agents' directory should be treated as a Python package.

# Set the default AppConfig for this Django application.
# This tells Django to use AiAgentsConfig (defined in apps.py) when loading this app.
default_app_config = 'ai_agents.apps.AiAgentsConfig'

# Optional: Define a package-level version for easier tracking.
VERSION = "1.0.0" 

# You can also make key classes from this package easily importable if desired, e.g.:
# from .main_orchestrator import PapriAIAgentOrchestrator
# from .query_understanding_agent import QueryUnderstandingAgent
# __all__ = ['PapriAIAgentOrchestrator', 'QueryUnderstandingAgent'] # Controls 'from ai_agents import *'

# For now, keeping it simple by just setting default_app_config is sufficient.
