# backend/payments/views.py
import logging
import uuid # For generating unique internal reference for payments
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.shortcuts import redirect, reverse # For redirecting after payment and building callback URL
from django.utils import timezone
from django.contrib.auth.models import User # To link payments/codes to users

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from .services import PaystackService
from api.models import SignupCode, UserProfile # Assuming SignupCode model is in api.models

logger = logging.getLogger(__name__)

# Utility to generate signup code value (can be moved to a utils.py)
import random
import string
def generate_unique_signup_code_value(length=8):
    # Ensure it's unique
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not SignupCode.objects.filter(code=code).exists():
            return code


class InitializePaystackPaymentView(APIView):
    permission_classes = [permissions.AllowAny] # Or IsAuthenticated if user must be logged in to pay

    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        amount_main_unit_str = request.data.get('amount') # e.g., "6" for $6 USD or "600" for NGN 600
        currency = request.data.get('currency', 'NGN').upper() # Default to NGN or your primary currency
        plan_name = request.data.get('plan_name', 'Papri Pro Subscription') # Example plan name

        if not email or not amount_main_unit_str:
            return Response({'error': 'Email and amount are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            amount_main_unit = Decimal(amount_main_unit_str)
            if amount_main_unit <= 0:
                raise ValueError("Amount must be positive.")
        except (InvalidOperation, ValueError):
            return Response({'error': 'Invalid amount format or value.'}, status=status.HTTP_400_BAD_REQUEST)

        # Convert to kobo/cents (Paystack expects amount in the smallest currency unit as an integer)
        # NGN, GHS, ZAR: amount * 100 (kobo/pesewas/cents)
        # USD, EUR, GBP: amount * 100 (cents/pence)
        # Check Paystack documentation for specific currency requirements.
        if currency in ['NGN', 'GHS', 'ZAR', 'USD', 'EUR', 'GBP']: # Add other relevant currencies
            amount_kobo = int(amount_main_unit * 100)
        else:
            logger.warning(f"Currency {currency} not explicitly configured for kobo/cent conversion. Assuming *100 factor.")
            amount_kobo = int(amount_main_unit * 100) # Fallback, verify this logic for new currencies

        # Generate a unique internal reference for this transaction attempt
        # This reference can be used to track the payment attempt in your system even before Paystack confirms.
        papri_internal_reference = f"PAPRI-{uuid.uuid4().hex[:10].upper()}-{timezone.now().strftime('%Y%m%d%H%M')}"

        # Define your callback URL (where Paystack redirects after payment attempt)
        try:
            callback_url = request.build_absolute_uri(reverse(settings.PAYSTACK_CALLBACK_URL_NAME))
        except Exception as e:
            logger.error(f"Could not reverse Paystack callback URL name '{settings.PAYSTACK_CALLBACK_URL_NAME}': {e}", exc_info=True)
            return Response({'error': 'Server configuration error for payment callback.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Metadata to pass to Paystack (optional, but useful for reconciliation)
        metadata = {
            "email": email,
            "papri_plan_name": plan_name,
            "papri_internal_reference": papri_internal_reference,
            "user_id_if_auth": str(request.user.id) if request.user.is_authenticated else None,
            "custom_fields": [ # Paystack specific metadata structure for display on their dashboard
                {"display_name": "Email", "variable_name": "customer_email", "value": email},
                {"display_name": "Plan", "variable_name": "subscription_plan", "value": plan_name},
                {"display_name": "Internal Ref", "variable_name": "papri_ref", "value": papri_internal_reference}
            ]
        }

        paystack_service = PaystackService()
        try:
            init_result = paystack_service.initialize_transaction(
                amount_kobo=amount_kobo,
                email=email,
                callback_url=callback_url,
                reference=papri_internal_reference, # Using our internal ref as Paystack's main ref
                metadata=metadata,
                currency=currency
            )
        except ValueError as ve: # e.g. if secret key not set in service
            logger.error(f"PaystackService configuration error: {ve}", exc_info=True)
            return Response({'error': f'Payment service configuration error: {str(ve)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


        if init_result.get('success'):
            logger.info(f"Paystack transaction initialized successfully for email {email}, ref {papri_internal_reference}. URL: {init_result.get('authorization_url')}")
            # Store initial transaction attempt details if you have a PaymentTransaction model
            # PaymentTransaction.objects.create(user=request.user if request.user.is_authenticated else None, email=email, ...)
            return Response({
                'success': True,
                'message': 'Transaction initialized. Redirecting to Paystack...',
                'authorization_url': init_result.get('authorization_url'),
                'access_code': init_result.get('access_code'), 
                'reference': init_result.get('reference') # This should be our papri_internal_reference
            }, status=status.HTTP_200_OK)
        else:
            logger.error(f"Paystack payment initialization failed for email {email}, ref {papri_internal_reference}. Error: {init_result.get('error')}")
            return Response({'error': init_result.get('error', 'Payment initialization failed with Paystack.')}, status=status.HTTP_400_BAD_REQUEST)


class PaystackCallbackView(APIView):
    permission_classes = [permissions.AllowAny] # Paystack will call this URL directly

    def get(self, request, *args, **kwargs):
        # Paystack typically includes 'reference' or 'trxref' in the query parameters
        transaction_reference = request.query_params.get('reference') or request.query_params.get('trxref')
        
        if not transaction_reference:
            logger.warning("Paystack callback called without a transaction reference.")
            # Redirect to a generic failure page on your frontend
            return redirect(f"{settings.PAYMENT_FAILED_REDIRECT_URL}?error=invalid_callback_noparam")

        logger.info(f"Received Paystack callback for transaction reference: {transaction_reference}")
        paystack_service = PaystackService()
        verification_result = paystack_service.verify_transaction(transaction_reference)

        # Determine redirect URLs based on outcome
        frontend_failure_url = settings.PAYMENT_FAILED_REDIRECT_URL
        frontend_success_url = settings.PAYMENT_SUCCESS_REDIRECT_URL

        if verification_result.get('success'):
            # Payment was successful on Paystack's end
            transaction_data = verification_result.get('data', {})
            email = transaction_data.get('customer', {}).get('email')
            amount_paid_kobo = transaction_data.get('amount') # Amount in kobo/cents
            currency_paid = transaction_data.get('currency')
            metadata_from_paystack = transaction_data.get('metadata', {}) # This will be a dict if you JSON.parsed it in service
            
            # If your metadata was a JSON string, you might need json.loads(metadata_from_paystack) here.
            # But Paystack often returns it as an object if it was sent as a JSON string.
            papri_plan_name = metadata_from_paystack.get('papri_plan_name', 'Default Plan') if isinstance(metadata_from_paystack, dict) else 'Default Plan'


            if not email:
                 logger.error(f"Paystack callback: Email not found in verified transaction data for ref {transaction_reference}.")
                 return redirect(f"{frontend_failure_url}?error=email_missing_on_verification&ref={transaction_reference}")

            # 1. Generate a unique Signup Code
            new_signup_code_value = generate_unique_signup_code_value()
            try:
                # Check if a user exists with this email, or create if part of your flow
                # For now, we assume the code is tied to the email, user activates later
                signup_code_obj, created = SignupCode.objects.update_or_create(
                    email=email, # Assuming one active (unused, unexpired) code per email for simplicity
                    is_used=False, # Only update/create if not already used
                    expires_at__gte=timezone.now(), # And not expired
                    defaults={
                        'code': new_signup_code_value,
                        'plan_name': papri_plan_name,
                        'payment_reference': transaction_reference, # Link to Paystack ref
                        'expires_at': timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS)
                    }
                )
                if not created and signup_code_obj.code != new_signup_code_value :
                    # An active code already exists, maybe re-issue or handle as per business logic
                    # For now, let's assume we overwrite with the new one if it's an update_or_create on an existing active entry
                    logger.warning(f"Updated existing active signup code for {email} to {new_signup_code_value}. Original: {signup_code_obj.code}")
                    signup_code_obj.code = new_signup_code_value
                    signup_code_obj.plan_name = papri_plan_name
                    signup_code_obj.payment_reference = transaction_reference
                    signup_code_obj.expires_at = timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS)
                    signup_code_obj.save()
                
                logger.info(f"Signup code {'generated' if created else 'updated'} for {email}: {signup_code_obj.code} (Ref: {transaction_reference})")
                
                # 2. TODO: Send email to user with the signup_code_obj.code (Consider Celery task for this)
                # from django.core.mail import send_mail
                # send_mail(
                #     f'Your {papri_plan_name} Signup Code for Papri',
                #     f'Thank you for your payment! Your Papri signup code is: {signup_code_obj.code}\n'
                #     f'Use this code to activate your plan on our website.\n'
                #     f'This code expires on {signup_code_obj.expires_at.strftime("%Y-%m-%d %H:%M")}.\n\n'
                #     f'Payment Details:\nReference: {transaction_reference}\nAmount: {Decimal(amount_paid_kobo)/100} {currency_paid}',
                #     settings.DEFAULT_FROM_EMAIL,
                #     [email],
                #     fail_silently=False, # Set to True if email failure shouldn't break flow
                # )

                # 3. Redirect user to a success page on your frontend.
                # Pass parameters to frontend to display relevant info.
                # Example: /app/#/payment-success?status=success&ref=XXXXXX&email=user@example.com&plan=PapriPro
                # The frontend can then guide the user or show the code.
                redirect_params = f"?status=success&ref={transaction_reference}&plan={papri_plan_name.replace(' ', '_')}"
                return redirect(f"{frontend_success_url}{redirect_params}")

            except Exception as e:
                logger.error(f"Error creating signup code or post-payment processing for {email} (Ref {transaction_reference}): {e}", exc_info=True)
                # Payment was successful with Paystack, but internal processing failed. Critical to log and possibly alert admins.
                # Redirect to a success page but indicate a potential delay or need for support.
                return redirect(f"{frontend_success_url}?status=pending_activation&ref={transaction_reference}&error=post_payment_processing_failed")

        else:
            # Payment verification failed or transaction was not successful on Paystack's end
            error_message = verification_result.get('error', 'Payment verification failed or payment was not successful.')
            logger.error(f"Paystack verification indicates failed or unconfirmed payment for reference {transaction_reference}: {error_message}")
            # Redirect user to a payment failed page on your frontend
            return redirect(f"{frontend_failure_url}?error={error_message[:100].replace(' ', '_')}&ref={transaction_reference}")


# Placeholder for a view to list subscription plans (could be static or dynamic)
class ListPlansView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, *args, **kwargs):
        # This would typically fetch plan details from DB or a config file
        plans = [
            {"id": "papri_pro_monthly", "name": "Papri Pro Monthly", "price": "6.00", "currency": "USD", "description": "Full access for one month."},
            {"id": "papri_pro_yearly", "name": "Papri Pro Yearly", "price": "60.00", "currency": "USD", "description": "Full access for one year (save 2 months)."},
        ]
        return Response(plans)
