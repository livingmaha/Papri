# backend/payments/views.py
import logging
import uuid
from decimal import Decimal, InvalidOperation
import json # For parsing webhook payload
import hashlib # For webhook signature
import hmac # For webhook signature

from django.conf import settings
from django.shortcuts import redirect, reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseServerError # For webhook response
from django.views.decorators.csrf import csrf_exempt # To exempt webhook view from CSRF
from django.utils.decorators import method_decorator # To apply csrf_exempt to CBV
from django.db import transaction # For atomic operations in webhook handling

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from .services import PaystackService
from api.models import SignupCode, UserProfile # Assuming SignupCode model is in api.models

logger = logging.getLogger(__name__)

def generate_unique_signup_code_value(length=8):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not SignupCode.objects.filter(code=code).exists():
            return code

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('payments_initiate', 'user_or_ip_key'), group='payments_initiate', rate=settings.RATELIMIT_DEFAULTS.get('payments_initiate', '10/h'), block=True), name='post')
class InitializePaystackPaymentView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        amount_main_unit_str = request.data.get('amount')
        currency = request.data.get('currency', 'NGN').upper()
        plan_name = request.data.get('plan_name', 'Papri Pro Subscription')

        if not email or not amount_main_unit_str:
            return Response({'error': 'Email and amount are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount_main_unit = Decimal(amount_main_unit_str)
            if amount_main_unit <= 0: raise ValueError("Amount must be positive.")
        except (InvalidOperation, ValueError):
            return Response({'error': 'Invalid amount format or value.'}, status=status.HTTP_400_BAD_REQUEST)

        if currency in ['NGN', 'GHS', 'ZAR', 'USD', 'EUR', 'GBP']:
            amount_kobo = int(amount_main_unit * 100)
        else:
            logger.warning(f"Currency {currency} not configured for kobo/cent conversion. Assuming *100.")
            amount_kobo = int(amount_main_unit * 100)

        papri_internal_reference = f"PAPRI-{uuid.uuid4().hex[:10].upper()}-{timezone.now().strftime('%Y%m%d%H%M')}"
        try:
            callback_url = request.build_absolute_uri(reverse(settings.PAYSTACK_CALLBACK_URL_NAME))
        except Exception as e:
            logger.error(f"Could not reverse Paystack callback URL '{settings.PAYSTACK_CALLBACK_URL_NAME}': {e}", exc_info=True)
            return Response({'error': 'Server config error for payment callback.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        metadata = {
            "email": email, "papri_plan_name": plan_name, "papri_internal_reference": papri_internal_reference,
            "user_id_if_auth": str(request.user.id) if request.user.is_authenticated else None,
            "custom_fields": [
                {"display_name": "Email", "variable_name": "customer_email", "value": email},
                {"display_name": "Plan", "variable_name": "subscription_plan", "value": plan_name},
                {"display_name": "Internal Ref", "variable_name": "papri_ref", "value": papri_internal_reference}
            ]
        }
        paystack_service = PaystackService()
        try:
            init_result = paystack_service.initialize_transaction(
                amount_kobo=amount_kobo, email=email, callback_url=callback_url,
                reference=papri_internal_reference, metadata=metadata, currency=currency
            )
        except ValueError as ve:
            logger.error(f"PaystackService config error: {ve}", exc_info=True)
            return Response({'error': f'Payment service config error: {str(ve)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if init_result.get('success'):
            logger.info(f"Paystack transaction initialized for {email}, ref {papri_internal_reference}. URL: {init_result.get('authorization_url')}")
            return Response({
                'success': True, 'message': 'Transaction initialized. Redirecting...',
                'authorization_url': init_result.get('authorization_url'),
                'access_code': init_result.get('access_code'), 'reference': init_result.get('reference')
            }, status=status.HTTP_200_OK)
        else:
            logger.error(f"Paystack init failed for {email}, ref {papri_internal_reference}. Error: {init_result.get('error')}")
            return Response({'error': init_result.get('error', 'Payment init failed.')}, status=status.HTTP_400_BAD_REQUEST)

class PaystackCallbackView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        transaction_reference = request.query_params.get('reference') or request.query_params.get('trxref')
        
        if not transaction_reference:
            logger.warning("Paystack callback without transaction reference.")
            return redirect(f"{settings.PAYMENT_FAILED_REDIRECT_URL}?error=invalid_callback_noparam")

        logger.info(f"Received Paystack callback for ref: {transaction_reference}")
        paystack_service = PaystackService()
        verification_result = paystack_service.verify_transaction(transaction_reference)

        frontend_failure_url = settings.PAYMENT_FAILED_REDIRECT_URL
        frontend_success_url = settings.PAYMENT_SUCCESS_REDIRECT_URL

        if verification_result.get('success'):
            transaction_data = verification_result.get('data', {})
            email = transaction_data.get('customer', {}).get('email')
            metadata_from_paystack = transaction_data.get('metadata', {})
            papri_plan_name = metadata_from_paystack.get('papri_plan_name', 'Default Plan') if isinstance(metadata_from_paystack, dict) else 'Default Plan'

            if not email:
                 logger.error(f"Paystack callback: Email missing for ref {transaction_reference}.")
                 return redirect(f"{frontend_failure_url}?error=email_missing_on_verification&ref={transaction_reference}")
            try:
                with transaction.atomic(): # Ensure code generation and UserProfile update is atomic
                    # Use the PaystackService to handle post-payment actions based on verified data
                    # This encapsulates the logic from the original view.
                    processed_ok, message = paystack_service.handle_successful_payment_for_signup_code(
                        email=email,
                        plan_name=papri_plan_name,
                        payment_reference=transaction_reference,
                        transaction_data=transaction_data # Pass full data for more context
                    )
                
                if processed_ok:
                    logger.info(f"Post-payment processing successful for {email} (Ref: {transaction_reference}). Message: {message}")
                    redirect_params = f"?status=success&ref={transaction_reference}&plan={papri_plan_name.replace(' ', '_')}"
                    # The message from handle_successful_payment might contain the signup code to pass to frontend if needed.
                    # For security, it's often better to email the code and not pass it in URL.
                    # If message contains code: redirect_params += f"&code={message.split(':')[-1].strip()}"
                    return redirect(f"{frontend_success_url}{redirect_params}")
                else:
                    logger.error(f"Post-payment processing FAILED for {email} (Ref {transaction_reference}): {message}")
                    return redirect(f"{frontend_success_url}?status=pending_activation&ref={transaction_reference}&error={message[:100].replace(' ', '_')}")

            except Exception as e: # Catch any other exception during our internal processing
                logger.error(f"Critical error in post-payment processing for {email} (Ref {transaction_reference}): {e}", exc_info=True)
                return redirect(f"{frontend_success_url}?status=pending_activation&ref={transaction_reference}&error=internal_processing_error")
        else:
            error_message = verification_result.get('error', 'Payment verification failed.')
            logger.error(f"Paystack verification failed for ref {transaction_reference}: {error_message}")
            return redirect(f"{frontend_failure_url}?error={error_message[:100].replace(' ', '_')}&ref={transaction_reference}")

class ListPlansView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, *args, **kwargs):
        plans = [
            {"id": "papri_pro_monthly", "name": "Papri Pro Monthly", "price": "6.00", "currency": "USD", "description": "Full access for one month."},
            {"id": "papri_pro_yearly", "name": "Papri Pro Yearly", "price": "60.00", "currency": "USD", "description": "Full access for one year (save 2 months)."},
        ]
        return Response(plans)

@method_decorator(csrf_exempt, name='dispatch') # Exempt from CSRF as Paystack won't send CSRF token
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('paystack_webhook', 'ip_key'), group='paystack_webhook', rate=settings.RATELIMIT_DEFAULTS.get('paystack_webhook', '60/m'), block=True), name='post')
class PaystackWebhookView(APIView):
    permission_classes = [permissions.AllowAny] # Webhook source is Paystack

    def post(self, request, *args, **kwargs):
        logger.info("Paystack webhook received.")
        paystack_service = PaystackService()
        
        # 1. Verify the webhook signature
        raw_payload = request.body
        paystack_signature = request.headers.get('X-Paystack-Signature')

        if not paystack_service.verify_webhook_signature(raw_payload, paystack_signature):
            logger.warning("Paystack webhook: Invalid signature. Request might be tampered or secret mismatch.")
            return HttpResponseForbidden("Invalid signature.")

        # 2. Parse the event payload
        try:
            event_payload = json.loads(raw_payload.decode('utf-8'))
            event_type = event_payload.get('event')
            event_data = event_payload.get('data') # This is the core data object
        except json.JSONDecodeError:
            logger.error("Paystack webhook: Could not decode JSON payload.")
            return HttpResponse("Invalid payload format.", status=400)
        except Exception as e:
            logger.error(f"Paystack webhook: Error parsing payload: {e}", exc_info=True)
            return HttpResponse("Error processing payload.", status=400)

        logger.info(f"Paystack webhook: Event type '{event_type}' received. Data keys: {event_data.keys() if event_data else 'No data'}")

        # 3. Process the event using the service layer
        try:
            with transaction.atomic(): # Ensure DB operations within handler are atomic
                success, message = paystack_service.handle_webhook_event(event_type, event_data)
            
            if success:
                logger.info(f"Paystack webhook event '{event_type}' processed successfully: {message}")
                return HttpResponse(status=200) # Important to return 200 OK to Paystack
            else:
                logger.error(f"Paystack webhook event '{event_type}' processing failed: {message}")
                # Still return 200 if error is application-side but event was received,
                # unless it's an error Paystack should retry (which is rare for successfully delivered webhooks).
                # Returning 500 might make Paystack retry, which could be problematic if not idempotent.
                return HttpResponseServerError(f"Webhook processing error: {message}")
        except Exception as e:
            logger.critical(f"Paystack webhook: Unhandled exception processing event '{event_type}': {e}", exc_info=True)
            # Critical error, signal server error to Paystack if appropriate
            return HttpResponseServerError("Internal server error processing webhook.")
