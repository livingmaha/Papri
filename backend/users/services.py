# backend/users/services.py
import logging
from django.contrib.auth import get_user_model
from django.db import transaction
from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models

# Import relevant models from other apps - use try-except for robustness
try:
    from api.models import SearchTask, VideoEditProject, EditTask, UserProfile
    from payments.models import PaymentTransaction, Subscription
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    SearchTask, VideoEditProject, EditTask, UserProfile = None, None, None, None
    PaymentTransaction, Subscription = None, None
    logging.warning("Could not import all models in users.services. RTBF might be incomplete.")

User = get_user_model()
logger = logging.getLogger(__name__)

def handle_rtbf_request(user_id: int) -> tuple[bool, str]:
    """
    Handles a Right to be Forgotten (RTBF) request for a given user.
    This function anonymizes or deletes user-related data.

    THIS IS A PRODUCTION-QUALITY STUB. It requires rigorous testing and legal
    consultation before being made fully operational, especially regarding
    file deletions and financial record handling.
    """
    if not MODELS_AVAILABLE:
        return False, "Service unavailable: Critical models could not be imported."

    try:
        with transaction.atomic():
            user_to_delete = User.objects.select_for_update().get(id=user_id)
            logger.info(f"Initiating RTBF process for user: {user_to_delete.username} (ID: {user_id})")

            anonymized_username = f"anonymized_user_{user_id}"
            anonymized_email = f"deleted_{user_id}@papri.example.com"

            # Anonymize SearchTasks
            if SearchTask:
                SearchTask.objects.filter(user=user_to_delete).update(
                    user=None, session_id=f"rtbf_anonymized_{user_id}",
                    query_text="[REDACTED BY RTBF]"
                    # Note: Physical deletion of query_image_ref files needs a separate, careful process.
                )
                logger.info(f"RTBF: Anonymized SearchTasks for user ID {user_id}.")

            # Anonymize VideoEditProjects and their child EditTasks
            if VideoEditProject and EditTask:
                user_projects = VideoEditProject.objects.filter(user=user_to_delete)
                for project in user_projects:
                    project.edit_tasks.update(
                        prompt_text="[REDACTED BY RTBF]",
                        # Note: Deleting result_media_path files requires a storage cleanup job.
                        result_media_path=None
                    )
                user_projects.update(user=None, project_name="Anonymized Project")
                logger.info(f"RTBF: Anonymized VideoEditProjects and EditTasks for user ID {user_id}.")

            # Anonymize PaymentTransactions
            # NOTE: Legal requirements often mandate keeping financial records.
            # This is anonymization, NOT deletion. Consult legal counsel.
            if PaymentTransaction:
                PaymentTransaction.objects.filter(user=user_to_delete).update(
                    user=None, email_for_guest=anonymized_email,
                    description=f"[ANONYMIZED] Original Txn for user {user_id}",
                    gateway_response_data={"status": "anonymized_by_rtbf"},
                    metadata={"status": "anonymized_by_rtbf"}
                )
                logger.info(f"RTBF: Anonymized PaymentTransactions for user ID {user_id}.")

            # Anonymize Subscriptions
            if Subscription:
                Subscription.objects.filter(user=user_to_delete).update(
                    user=None, status='cancelled_by_admin',
                    notes=f"Anonymized due to RTBF for user ID {user_id}."
                )
                logger.info(f"RTBF: Anonymized Subscriptions for user ID {user_id}.")

            # Data in Qdrant (Vector DB)
            # This part is highly dependent on your data schema in Qdrant.
            # If user-specific data is stored with a user_id payload, it can be deleted.
            # For PAPRI, user data is mostly transient (search queries) or linked
            # to projects. If a user *uploads* a video that gets indexed, its
            # corresponding `video_source_id` would be the key to deletion.
            # This stub assumes no such direct user-owned indexed content for now.
            logger.info(f"RTBF: Qdrant data processing placeholder for user ID {user_id}. No direct user-owned vectors assumed in current schema.")

            # Delete the UserProfile
            if hasattr(user_to_delete, 'profile'):
                user_to_delete.profile.delete()
                logger.info(f"RTBF: Deleted UserProfile for user ID {user_id}.")

            # Finally, anonymize and deactivate the User object
            user_to_delete.username = anonymized_username
            user_to_delete.email = anonymized_email
            user_to_delete.first_name = ""
            user_to_delete.last_name = ""
            user_to_delete.is_active = False
            user_to_delete.is_staff = False
            user_to_delete.is_superuser = False
            user_to_delete.set_unusable_password()
            user_to_delete.save()
            logger.info(f"RTBF: Anonymized and deactivated User object for ID {user_id}.")

            logger.info(f"RTBF: Process completed for user ID {user_id}.")
            return True, f"RTBF process completed successfully for user ID {user_id}."

    except User.DoesNotExist:
        logger.error(f"RTBF Error: User with ID {user_id} not found.")
        return False, f"User with ID {user_id} not found."
    except Exception as e:
        logger.critical(f"RTBF CRITICAL ERROR for user ID {user_id}: {str(e)}", exc_info=True)
        return False, f"An unexpected error occurred during RTBF process."
