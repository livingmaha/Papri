# backend/payments/services.py
import requests
import os
import json
import logging
import hmac # For webhook signature verification
import hashlib # For webhook signature verification
from decimal import Decimal # For amount conversions
from django.utils import timezone
from django.contrib.auth.models import User

from django.conf import settings
from django.db import transaction # For atomic operations

# Import relevant models
# Assuming SignupCode and UserProfile are in api.models
from api.models import SignupCode, UserProfile 
from .models import PaymentTransaction, Subscription # Models from the payments app

logger = logging.getLogger(__name__)

# Utility to generate signup code value (can be moved to a utils.py or shared)
import random
import string
def generate_unique_signup_code_value(length=8):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not SignupCode.objects.filter(code=code).exists():
            return code

class PaystackService:
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.public_key = settings.PAYSTACK_PUBLIC_KEY
        self.webhook_secret = settings.PAYSTACK_WEBHOOK_SECRET # ADDED
        self.base_url = "https://api.paystack.co"

        if not self.secret_key:
            logger.critical("PAYSTACK_SECRET_KEY is not set in Django settings!")
        if not self.webhook_secret: # ADDED check
            logger.warning("PAYSTACK_WEBHOOK_SECRET is not set. Webhook verification will fail.")


    def _get_headers(self):
        if not self.secret_key:
            raise ValueError("Paystack secret key is not configured.")
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }

    def initialize_transaction(self, amount_kobo: int, email: str, callback_url: str, reference: str = None, metadata: dict = None, currency: str = "NGN"):
        url = f"{self.base_url}/transaction/initialize"
        payload = {
            "email": email, "amount": str(amount_kobo), "currency": currency,
            "callback_url": callback_url,
        }
        if reference: payload["reference"] = reference
        if metadata: payload["metadata"] = json.dumps(metadata)
        logger.debug(f"Paystack initialize payload: {payload}")
        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Paystack initialize response: {data}")
            if data.get("status") is True:
                return {
                    "success": True, "authorization_url": data["data"]["authorization_url"],
                    "access_code": data["data"]["access_code"], "reference": data["data"]["reference"],
                }
            else:
                return {"success": False, "error": data.get("message", "Init failed.")}
        except requests.exceptions.HTTPError as http_err:
            # ... (existing error handling) ...
            error_content = http_err.response.text if http_err.response else "No response content"
            logger.error(f"Paystack API HTTP error (initialize): {http_err}. Response: {error_content[:200]}", exc_info=True)
            return {"success": False, "error": f"Paystack API error: {str(http_err)}. Details: {error_content[:200]}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API request error (initialize): {e}", exc_info=True)
            return {"success": False, "error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error initializing Paystack txn: {e}", exc_info=True)
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def verify_transaction(self, reference: str):
        if not reference: return {"success": False, "error": "Reference cannot be empty."}
        url = f"{self.base_url}/transaction/verify/{reference}"
        logger.debug(f"Verifying Paystack transaction ref: {reference}")
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Paystack verify response for ref '{reference}': {data}")
            if data.get("status") is True:
                transaction_status = data["data"].get("status")
                if transaction_status == "success":
                    return {"success": True, "message": "Transaction successful.", "data": data["data"]}
                else:
                    return {"success": False, "error": f"Payment not successful. Status: {transaction_status}. Gateway: {data['data'].get('gateway_response', 'N/A')}", "data": data["data"]}
            else:
                return {"success": False, "error": data.get("message", "Verification API call failed.")}
        # ... (existing error handling for verify_transaction) ...
        except requests.exceptions.HTTPError as http_err:
            error_content = http_err.response.text if http_err.response else "No response content"
            if http_err.response.status_code == 404:
                 logger.warning(f"Paystack verify: Txn ref '{reference}' not found (404).")
                 return {"success": False, "error": f"Txn ref '{reference}' not found."}
            logger.error(f"Paystack API HTTP error (verify ref '{reference}'): {http_err}. Response: {error_content[:200]}", exc_info=True)
            return {"success": False, "error": f"Paystack API error: {str(http_err)}. Details: {error_content[:200]}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API request error (verify ref '{reference}'): {e}", exc_info=True)
            return {"success": False, "error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error verifying Paystack txn '{reference}': {e}", exc_info=True)
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


    def handle_successful_payment_for_signup_code(self, email: str, plan_name: str, payment_reference: str, transaction_data: dict) -> tuple[bool, str]:
        """
        Handles post-payment logic specifically for creating a SignupCode.
        This is typically called from the PaystackCallbackView after successful verification.
        """
        try:
            new_signup_code_value = generate_unique_signup_code_value()
            # Using update_or_create to handle cases where a user might try to pay again for the same email
            # before using a previous code. This logic might need refinement based on business rules.
            signup_code_obj, created = SignupCode.objects.update_or_create(
                email=email,
                is_used=False,
                expires_at__gte=timezone.now(),
                defaults={
                    'code': new_signup_code_value,
                    'plan_name': plan_name,
                    'payment_reference': payment_reference,
                    'expires_at': timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS)
                }
            )
            if not created: # An existing active, unused code for this email was updated
                logger.warning(f"Updated existing active signup code for {email} to {new_signup_code_value}. Original: {signup_code_obj.code}. New Expiry: {signup_code_obj.expires_at}")
            
            logger.info(f"Signup code {'generated' if created else 'updated'} for {email}: {signup_code_obj.code} (Ref: {payment_reference})")
            
            # TODO: Implement robust email sending (e.g., via a Celery task)
            # mail_subject = f"Your {plan_name} Activation Code for Papri"
            # mail_message = f"Thank you for your payment! Your Papri activation code is: {signup_code_obj.code}\n..."
            # send_mail(mail_subject, mail_message, settings.DEFAULT_FROM_EMAIL, [email])
            
            return True, f"Signup code {signup_code_obj.code} generated/updated for {email}."
        except Exception as e:
            logger.error(f"Error in handle_successful_payment_for_signup_code for {email} (Ref {payment_reference}): {e}", exc_info=True)
            return False, "Internal error processing payment outcome."

    # --- Webhook Specific Methods ---
    def verify_webhook_signature(self, payload_body: bytes, paystack_signature: Optional[str]) -> bool:
        """Verifies the Paystack webhook signature."""
        if not self.webhook_secret:
            logger.error("Paystack webhook secret not configured. Cannot verify signature.")
            # Depending on policy, either allow unverified (risky) or deny. For now, deny.
            return False
        if not paystack_signature:
            logger.warning("Paystack webhook: Missing X-Paystack-Signature header.")
            return False

        try:
            hash_val = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload_body,
                hashlib.sha512
            ).hexdigest()
            if hmac.compare_digest(hash_val, paystack_signature):
                logger.debug("Paystack webhook signature verified successfully.")
                return True
            else:
                logger.warning(f"Paystack webhook: Signature mismatch. Calculated: {hash_val}, Received: {paystack_signature}")
                return False
        except Exception as e:
            logger.error(f"Error during Paystack webhook signature verification: {e}", exc_info=True)
            return False

    @transaction.atomic # Ensure database operations within event handlers are atomic
    def handle_webhook_event(self, event_type: str, event_data: dict) -> tuple[bool, str]:
        """
        Processes a verified Paystack webhook event.
        Returns (True, "Success message") or (False, "Error message").
        """
        logger.info(f"Handling Paystack webhook event: {event_type}")
        
        # Example: Log the event to PaymentTransaction if reference exists
        reference = event_data.get('reference')
        if reference:
            PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(
                status='webhook_processing', # Indicate we're looking at it
                webhook_event_data=event_data, # Store the payload
                updated_at=timezone.now()
            )

        if event_type == 'charge.success':
            # This often means a one-time payment was successful or an invoice for a subscription was paid.
            # The primary logic for signup code generation or initial UserProfile update
            # is typically handled in PaystackCallbackView for immediate user feedback.
            # Webhooks serve as a reliable confirmation or for events not tied to direct user flow.
            
            email = event_data.get('customer', {}).get('email')
            amount = event_data.get('amount') # in kobo/cents
            currency = event_data.get('currency')
            paystack_ref = event_data.get('reference')
            status = event_data.get('status') # should be 'success'
            plan_name_from_metadata = event_data.get('metadata', {}).get('papri_plan_name', 'Papri Pro Plan from Webhook')

            logger.info(f"Webhook 'charge.success': Ref={paystack_ref}, Email={email}, Amount={amount}{currency}, Status={status}")

            if not email or not paystack_ref or status != 'success':
                msg = f"Webhook 'charge.success' ignored: Missing email, reference, or status not 'success'. Data: {str(event_data)[:200]}"
                logger.warning(msg)
                if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message=msg)
                return False, msg
            
            # Idempotency: Check if already processed via callback or another webhook
            # This is simplified; real idempotency might involve checking PaymentTransaction status or specific flags.
            if SignupCode.objects.filter(payment_reference=paystack_ref, is_used=False).exists():
                 logger.info(f"Webhook 'charge.success': Signup code for ref {paystack_ref} likely already created by callback. Verifying state.")
                 # Optionally, re-verify user profile or ensure email with code was sent.
                 if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok')
                 return True, "Charge success event noted, likely already handled by callback."

            # If callback might have missed or if this is the primary mechanism for some plans:
            # Create/update UserProfile and SignupCode.
            user, _ = User.objects.get_or_create(email=email, defaults={'username': email})
            user_profile, _ = UserProfile.objects.get_or_create(user=user)
            
            # This duplicates logic from callback view for robustness if callback fails.
            # Consider extracting to a shared utility function.
            new_code_val = generate_unique_signup_code_value()
            signup_code, sc_created = SignupCode.objects.update_or_create(
                email=email, is_used=False, expires_at__gte=timezone.now(),
                defaults={
                    'code': new_code_val, 'plan_name': plan_name_from_metadata,
                    'payment_reference': paystack_ref,
                    'expires_at': timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS)
                }
            )
            logger.info(f"Webhook 'charge.success': SignupCode {'created' if sc_created else 'updated'} for {email}: {signup_code.code}")
            
            # Update UserProfile based on this successful charge
            user_profile.subscription_plan = plan_name_from_metadata.lower().replace(" ", "_") # Ensure consistent plan key
            user_profile.subscription_expiry_date = timezone.now() + timezone.timedelta(days=30) # Example: 30 days access for generic charge
            user_profile.remaining_trial_searches = 0 # Clear trials
            user_profile.save()
            logger.info(f"Webhook 'charge.success': UserProfile for {email} updated to plan {user_profile.subscription_plan}.")

            if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok', signup_code_generated=signup_code)
            return True, "Charge successful, user profile and signup code processed via webhook."

        elif event_type == 'subscription.create':
            # User subscribed to a new plan via Paystack's subscription product
            customer_code = event_data.get('customer', {}).get('customer_code')
            customer_email = event_data.get('customer', {}).get('email')
            subscription_code = event_data.get('subscription_code')
            plan_code_paystack = event_data.get('plan', {}).get('plan_code')
            plan_name_paystack = event_data.get('plan', {}).get('name', 'Unknown Paystack Plan')
            amount_kobo = event_data.get('amount') # Amount per interval
            status = event_data.get('status') # e.g., 'active', 'incomplete'
            next_payment_date_str = event_data.get('next_payment_date')
            
            logger.info(f"Webhook 'subscription.create': SubCode={subscription_code}, Plan={plan_name_paystack}, Email={customer_email}, Status={status}")
            
            if not customer_email or not subscription_code:
                msg = f"'subscription.create' webhook ignored: Missing email or subscription_code. Data: {str(event_data)[:200]}"
                logger.warning(msg)
                if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message=msg)
                return False, msg

            user, _ = User.objects.get_or_create(email=customer_email, defaults={'username': customer_email})
            user_profile, _ = UserProfile.objects.get_or_create(user=user)
            
            # Map Paystack plan_code/name to your internal plan_name_papri
            # This mapping needs to be robust. For example:
            internal_plan_name = 'papri_pro_monthly' # Default
            if plan_name_paystack and "yearly" in plan_name_paystack.lower():
                internal_plan_name = 'papri_pro_yearly'
            
            subscription_record, created = Subscription.objects.update_or_create(
                user=user,
                gateway_subscription_code=subscription_code, # Use this as a unique key for Paystack subscriptions
                defaults={
                    'plan_name_papri': internal_plan_name,
                    'status': status, # Paystack's status directly ('active', 'incomplete', etc.)
                    'start_date': timezone.now() if status == 'active' else None,
                    'end_date': None, # Typically for recurring, end_date is managed by renewal or cancellation
                    'next_payment_date': timezone.make_aware(datetime.fromisoformat(next_payment_date_str)) if next_payment_date_str else None,
                    'gateway_customer_code': customer_code,
                    'auto_renew': True, # Assume auto-renew by default for Paystack subscriptions
                }
            )
            logger.info(f"Subscription record {'created' if created else 'updated'} for user {user.email}: {subscription_record}")

            if status == 'active':
                user_profile.subscription_plan = internal_plan_name
                user_profile.subscription_id_gateway = subscription_code
                user_profile.subscription_expiry_date = subscription_record.next_payment_date # Or derive based on plan interval
                user_profile.save()
                logger.info(f"UserProfile for {user.email} updated for active Paystack subscription {subscription_code}.")
            
            if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok')
            return True, f"Subscription {subscription_code} event processed."

        elif event_type == 'subscription.disable':
            subscription_code = event_data.get('subscription_code')
            customer_email = event_data.get('customer', {}).get('email') # May not always be present if only sub_code
            logger.info(f"Webhook 'subscription.disable': SubCode={subscription_code}, Email={customer_email}")

            try:
                sub_record = Subscription.objects.get(gateway_subscription_code=subscription_code)
                sub_record.status = 'cancelled_by_admin' # Or derive specific reason, e.g. 'cancelled_by_gateway'
                sub_record.auto_renew = False
                sub_record.cancelled_at_gateway = timezone.now()
                sub_record.end_date = sub_record.next_payment_date or timezone.now() # Set end date
                sub_record.save()

                user_profile = UserProfile.objects.get(user=sub_record.user)
                user_profile.subscription_plan = 'cancelled' # Or 'free_trial' if downgrading
                user_profile.subscription_id_gateway = None # Clear gateway sub ID
                user_profile.save()
                logger.info(f"Subscription {subscription_code} disabled for user {sub_record.user.email}. Profile updated.")
                if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok')
            except Subscription.DoesNotExist:
                logger.warning(f"Received 'subscription.disable' for unknown subscription_code {subscription_code}")
                if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message=f"Unknown sub code {subscription_code}")
                return False, f"Subscription record for code {subscription_code} not found."
            except UserProfile.DoesNotExist:
                 logger.warning(f"UserProfile not found for user of subscription {subscription_code} during disable.")
                 if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message=f"UserProfile not found for sub {subscription_code}")
            return True, f"Subscription {subscription_code} disable event processed."

        elif event_type == 'invoice.payment_failed' or event_type == 'invoice.update': # renewal failed or other invoice update
            # For recurring payments. If an invoice payment fails.
            subscription_code = event_data.get('subscription', {}).get('subscription_code')
            customer_email = event_data.get('customer', {}).get('email')
            invoice_status = event_data.get('status') # e.g., 'failed', 'pending'
            
            logger.info(f"Webhook '{event_type}': SubCode={subscription_code}, Email={customer_email}, InvoiceStatus={invoice_status}")
            if subscription_code:
                try:
                    sub_record = Subscription.objects.get(gateway_subscription_code=subscription_code)
                    if invoice_status == 'failed':
                        sub_record.status = 'past_due' # Or 'unpaid' depending on Paystack's grace period logic
                        # Log this, maybe notify user, but don't disable access immediately if there are retries.
                        sub_record.save()
                        logger.warning(f"Invoice payment FAILED for subscription {subscription_code}. Status set to {sub_record.status}.")
                    elif invoice_status == 'success' and event_type == 'invoice.update': # If invoice.update shows a successful payment
                        sub_record.status = 'active'
                        sub_record.next_payment_date = timezone.make_aware(datetime.fromisoformat(event_data.get('subscription',{}).get('next_payment_date'))) if event_data.get('subscription',{}).get('next_payment_date') else None
                        sub_record.start_date = sub_record.start_date or timezone.now() # Ensure start date is set
                        sub_record.end_date = None # For active auto-renewing
                        sub_record.save()
                        logger.info(f"Invoice successfully PAID for subscription {subscription_code}. Status set to {sub_record.status}.")
                        # Update UserProfile
                        user_profile = UserProfile.objects.get(user=sub_record.user)
                        user_profile.subscription_plan = sub_record.plan_name_papri
                        user_profile.subscription_expiry_date = sub_record.next_payment_date
                        user_profile.save()

                    if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok')
                except Subscription.DoesNotExist:
                    logger.warning(f"Received '{event_type}' for unknown subscription_code {subscription_code}")
                    if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message=f"Unknown sub code {subscription_code}")
                    return False, f"Subscription record for code {subscription_code} not found."
            return True, f"Invoice event '{event_type}' processed."

        # Add handlers for other events like:
        # - subscription.not_renew (if user cancels auto-renew on Paystack dashboard)
        # - customeridentification.failed / .success
        # - transfer.success / .failed (if using Paystack transfers)
        
        else:
            logger.info(f"Paystack webhook: Unhandled event type '{event_type}'. Payload: {str(event_data)[:300]}")
            # If reference exists, mark as processed with note, but don't fail if unhandled.
            if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processed_ok', processing_error_message=f"Unhandled event: {event_type}")
            return True, f"Unhandled event type: {event_type}"
        
        # Should not be reached if all branches return
        if reference: PaymentTransaction.objects.filter(gateway_transaction_id=reference).update(status='webhook_processing_failed', processing_error_message="Reached end of webhook handler unexpectedly.")
        return False, "Event handler logic incomplete."
