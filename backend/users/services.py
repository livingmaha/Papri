# backend/users/services.py
import logging
from django.contrib.auth import get_user_model
from django.db import transaction
from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models

# Import relevant models from other apps - use try-except for robustness if apps might not exist
try:
    from api.models import SearchTask, EditTask, VideoSource, VideoFrameFeature, Transcript
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    logger.warning("Could not import all models from 'api' app in users.services. RTBF might be incomplete.")
    SearchTask, EditTask, VideoSource, VideoFrameFeature, Transcript = None, None, None, None, None


try:
    from payments.models import PaymentTransaction, Subscription
    PAYMENT_MODELS_AVAILABLE = True
except ImportError:
    PAYMENT_MODELS_AVAILABLE = False
    logger.warning("Could not import models from 'payments' app in users.services. RTBF financial data handling might be incomplete.")
    PaymentTransaction, Subscription = None, None


User = get_user_model()
logger = logging.getLogger(__name__)

def handle_rtbf_request(user_id: int) -> tuple[bool, str]:
    """
    Handles a Right to be Forgotten (RTBF) request for a given user.

    This function outlines the conceptual steps for anonymizing or deleting 
    user-related data. The actual implementation requires careful consideration 
    of data relationships, legal obligations (e.g., data retention for financial 
    records), and cascading effects.

    THIS IS A STUB AND REQUIRES FULL IMPLEMENTATION, TESTING, AND LEGAL REVIEW.

    Args:
        user_id (int): The ID of the user requesting data deletion.

    Returns:
        tuple[bool, str]: (True, "Success message") or (False, "Error message").
    """
    try:
        with transaction.atomic(): # Wrap operations in a transaction
            user_to_delete = User.objects.get(id=user_id)
            logger.info(f"Initiating RTBF process for user: {user_to_delete.username} (ID: {user_id})")

            # Step 1: Verify user identity/authorization (Assumed to be done before calling this service)
            # This function should only be callable by authorized internal processes after verification.

            # Step 2: Identify and process all user-related data
            anonymized_username = f"anonymized_user_{user_id}"
            anonymized_email = f"deleted_{user_id}@papri.example.com" # Ensure this is a non-functional domain

            # a) SearchTask entries
            if SearchTask and MODELS_AVAILABLE:
                SearchTask.objects.filter(user=user_to_delete).update(
                    user=None, # Anonymize by detaching from user
                    session_id=f"rtbf_anonymized_{user_id}", # Anonymize session if tied
                    query_text="[REDACTED BY RTBF]",
                    # Consider if query_image_ref needs deletion from storage
                )
                logger.info(f"RTBF: Anonymized SearchTasks for user ID {user_id}.")

            # b) EditTask and VideoEditProject entries
            if VideoEditProject and EditTask and MODELS_AVAILABLE:
                # For EditTasks, anonymize prompts and results if they contain PII.
                # Detach projects from the user.
                user_projects = VideoEditProject.objects.filter(user=user_to_delete)
                for project in user_projects:
                    EditTask.objects.filter(project=project).update(
                        prompt_text="[REDACTED BY RTBF]",
                        # Consider deleting result_media_path files if they contain PII or are user-owned
                        # For now, just clear the path from DB. Actual file deletion is complex.
                        result_media_path=None 
                    )
                    project.user = None
                    project.project_name = f"Anonymized Project {project.id}"
                    # Consider deleting uploaded_video_path files if they are user-specific.
                    project.uploaded_video_path = None 
                    project.save()
                logger.info(f"RTBF: Anonymized VideoEditProjects and EditTasks for user ID {user_id}.")
            
            # c) PaymentTransaction and Subscription (LIKELY REQUIRES ANONYMIZATION, NOT FULL DELETION)
            if PaymentTransaction and PAYMENT_MODELS_AVAILABLE:
                PaymentTransaction.objects.filter(user=user_to_delete).update(
                    user=None, 
                    email_for_guest=anonymized_email, # Anonymize email if it was user's
                    description=f"[REDACTED BY RTBF] Original Txn for user {user_id}",
                    # Gateway response might contain PII, consider selective redaction or full nullification
                    # gateway_response_data = {"status": "anonymized_rtbf"},
                    # metadata = {"status": "anonymized_rtbf"},
                )
                logger.info(f"RTBF: Anonymized PaymentTransactions for user ID {user_id}.")

            if Subscription and PAYMENT_MODELS_AVAILABLE:
                # Subscriptions might need to be cancelled at gateway first if active.
                # This stub assumes cancellation is handled elsewhere or focuses on DB anonymization.
                Subscription.objects.filter(user=user_to_delete).update(
                    user=None, # Detach
                    status='cancelled_rtbf', 
                    notes=f"Anonymized due to RTBF for user ID {user_id}. Original status may vary.",
                    # gateway_customer_code and gateway_subscription_code may need to be kept for audit
                    # or anonymized carefully if they are PII.
                )
                logger.info(f"RTBF: Anonymized/Cancelled Subscriptions for user ID {user_id}.")

            # d) Data in Qdrant (vector DB) - This is highly dependent on your payload structure.
            # Assuming Qdrant collections store `user_id` in payload if vectors are user-specific.
            # If videos/frames are processed by users and linked, those might need to be handled.
            # This example is very conceptual.
            if settings.QDRANT_URL and MODELS_AVAILABLE: # Check if Qdrant is configured
                try:
                    qdrant_client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=10)
                    
                    # Example for transcript segments if user_id was part of payload (unlikely for this app's design)
                    # qdrant_client.delete(
                    #     collection_name=settings.QDRANT_TRANSCRIPT_COLLECTION_NAME,
                    #     points_selector=qdrant_models.FilterSelector(
                    #         filter=qdrant_models.Filter(must=[
                    #             qdrant_models.FieldCondition(key="user_db_id", match=qdrant_models.MatchValue(value=str(user_id)))
                    #         ])
                    #     )
                    # )
                    # logger.info(f"RTBF: Attempted to delete Qdrant transcript points linked to user ID {user_id}.")
                    
                    # If user-uploaded videos for editing were indexed in Qdrant via VideoSource/VideoFrameFeature,
                    # those VideoSource objects would need to be identified and their Qdrant points deleted.
                    # This example doesn't cover that complex case, as VideoSource is more for public videos.
                    
                    logger.info(f"RTBF: Qdrant data processing placeholder for user ID {user_id}. Actual logic depends on schema.")
                except Exception as e_qdrant:
                    logger.error(f"RTBF: Error during Qdrant data processing for user ID {user_id}: {e_qdrant}")
                    # Do not let Qdrant failure stop the rest of the RTBF process for critical PII.

            # e) UserProfile
            if hasattr(user_to_delete, 'profile'):
                user_to_delete.profile.delete() # Or anonymize fields if preferred
                logger.info(f"RTBF: Deleted UserProfile for user ID {user_id}.")

            # f) Finally, handle the User object itself.
            # Option 1: Anonymize (safer for foreign key integrity if not all relations are SET_NULL)
            user_to_delete.username = anonymized_username
            user_to_delete.email = anonymized_email
            user_to_delete.first_name = "[REDACTED]"
            user_to_delete.last_name = "[REDACTED]"
            user_to_delete.is_active = False
            user_to_delete.is_staff = False
            user_to_delete.is_superuser = False
            user_to_delete.set_unusable_password()
            user_to_delete.save()
            logger.info(f"RTBF: Anonymized and deactivated User object for ID {user_id}.")

            # Option 2: Delete (if all relations are CASCADE or SET_NULL and you are sure)
            # user_to_delete.delete()
            # logger.info(f"RTBF: Deleted User object for ID {user_id}.")


            # Step 3: Log the action securely
            # (e.g., to a separate, restricted audit log)
            logger.info(f"RTBF: Action completed and logged for user ID {user_id}.")

            # Step 4: Confirm completion (e.g., internal notification)
            return True, f"RTBF process completed for user ID {user_id}."

    except User.DoesNotExist:
        logger.error(f"RTBF Error: User with ID {user_id} not found.")
        return False, f"User with ID {user_id} not found."
    except Exception as e:
        logger.error(f"RTBF Error for user ID {user_id}: {str(e)}", exc_info=True)
        # If transaction fails, it will roll back.
        return False, f"An unexpected error occurred during RTBF process: {str(e)}"
