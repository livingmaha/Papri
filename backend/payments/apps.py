# backend/payments/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payments' # Must match the app directory name
    verbose_name = "Papri Payments Management"

    def ready(self):
        logger.info(f"Initializing {self.verbose_name} application...")
        # You can connect signals or perform other app-specific initializations here if needed.
        # For example: from . import signals
        logger.info(f"{self.verbose_name} application ready.")
