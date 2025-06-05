# backend/payments/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings # For default_signup_code_expiry if needed here
import uuid

# Import models from other apps if needed for ForeignKey, but be mindful of circular dependencies.
# from api.models import SignupCode # SignupCode is defined in api.models, this import creates circularity if used directly for ForeignKey.
# If linking SignupCode from api.models, use a string reference: 'api.SignupCode'

logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
    Records details of each payment attempt or completed transaction.
    """
    GATEWAY_CHOICES = [
        ('paystack', 'Paystack'),
        ('stripe', 'Stripe'),
        ('manual', 'Manual/Admin'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending_init', 'Pending Initialization'),
        ('initiated', 'Initiated (User at Gateway)'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
        ('abandoned', 'Abandoned by User'),
        ('error', 'Gateway Error'),
        ('refunded', 'Refunded'),
        ('disputed', 'Disputed'),
        ('webhook_processing', 'Webhook Processing'), # New status
        ('webhook_processed_ok', 'Webhook Processed OK'), # New status
        ('webhook_processing_failed', 'Webhook Processing Failed'), # New status
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transactions', help_text="User who made/initiated the payment, if authenticated.")
    email_for_guest = models.EmailField(null=True, blank=True, help_text="Email used if payment was by an unauthenticated user.")
    
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount of the transaction.")
    currency = models.CharField(max_length=3, default='USD', help_text="Currency code (e.g., USD, NGN).")
    
    payment_gateway = models.CharField(max_length=50, choices=GATEWAY_CHOICES, default='paystack')
    gateway_transaction_id = models.CharField(max_length=255, unique=True, db_index=True, help_text="Unique transaction ID from the payment gateway (e.g., Paystack reference).")
    papri_internal_reference = models.CharField(max_length=255, unique=True, db_index=True, null=True, blank=True, help_text="Papri's internal unique reference for this attempt.")
    
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_init', db_index=True) # Increased length
    description = models.CharField(max_length=255, null=True, blank=True, help_text="Short description of the payment (e.g., 'Papri Pro Monthly Subscription').")
    
    gateway_response_data = models.JSONField(null=True, blank=True, help_text="Raw response or key details from the payment gateway (e.g. from verification).")
    webhook_event_data = models.JSONField(null=True, blank=True, help_text="Raw data received from a webhook event related to this transaction.")
    metadata = models.JSONField(null=True, blank=True, help_text="Any additional metadata associated with the transaction.")

    # Link to SignupCode if one was generated for this transaction.
    # Use string 'app_label.ModelName' to avoid circular import if SignupCode is in api.models
    signup_code_generated = models.OneToOneField(
        'api.SignupCode', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='generated_by_payment_transaction' # Changed related_name
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"

    def __str__(self):
        user_identifier = self.user.username if self.user else self.email_for_guest or "Guest"
        return f"Txn {self.gateway_transaction_id or self.id} by {user_identifier} for {self.amount} {self.currency} ({self.get_status_display()})"


class Subscription(models.Model):
    """
    Manages user subscriptions to Papri plans. This model is more for subscriptions managed
    by Paystack's subscription product. If using one-time payments to grant access (via SignupCode),
    the UserProfile model might be the primary source of truth for access period.
    """
    PLAN_CHOICES = [
        ('free_trial', 'Free Trial'), # Added free_trial here to align with UserProfile
        ('papri_pro_monthly', 'Papri Pro Monthly'),
        ('papri_pro_yearly', 'Papri Pro Yearly'),
        # Add other plans as needed
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('pending_activation', 'Pending Activation'),
        ('past_due', 'Past Due'), # Payment failed, grace period might apply
        ('unpaid', 'Unpaid'), # Payment definitively failed, access usually revoked
        ('cancelled_by_user', 'Cancelled by User'),
        ('cancelled_by_admin', 'Cancelled by Admin'),
        ('cancelled_payment_failure', 'Cancelled (Payment Failure)'), # After retries failed
        ('expired', 'Expired'), # Naturally ended
        ('incomplete', 'Incomplete (Paystack)'), # Subscription initiated but not fully set up
        ('incomplete_expired', 'Incomplete Expired (Paystack)'),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='papri_subscription_record', help_text="The subscribed user.")
    plan_name_papri = models.CharField(max_length=100, choices=PLAN_CHOICES, help_text="The specific Papri plan name.")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending_activation', db_index=True)
    
    start_date = models.DateTimeField(null=True, blank=True, help_text="Date subscription became active.")
    end_date = models.DateTimeField(null=True, blank=True, help_text="Date subscription expires/expired. Null if ongoing (e.g. auto-renewing).")
    next_payment_date = models.DateTimeField(null=True, blank=True, help_text="For recurring subscriptions, when the next payment is due.")
    
    gateway_customer_code = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Customer code from payment gateway (e.g., Paystack customer code).")
    gateway_subscription_code = models.CharField(max_length=255, null=True, blank=True, unique=True, db_index=True, help_text="Subscription code from payment gateway (e.g., Paystack Subscription Code).")
    # Link to the payment transaction that activated or last renewed this subscription
    latest_payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='renewed_subscriptions')
    
    auto_renew = models.BooleanField(default=True, help_text="Does this subscription auto-renew via the payment gateway by default?")
    cancelled_at_gateway = models.DateTimeField(null=True, blank=True, help_text="Timestamp if the subscription was cancelled at the gateway.")
    
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = "User Subscription Record"
        verbose_name_plural = "User Subscription Records"

    def __str__(self):
        return f"{self.get_plan_name_papri_display()} for {self.user.username} (Status: {self.get_status_display()})"

    @property # Changed from method to property
    def is_currently_active(self) -> bool:
        """Checks if the subscription is currently considered active for granting access."""
        if self.status == 'active':
            if self.end_date: # Fixed-term active subscription
                return timezone.now() < self.end_date
            return True # Ongoing active subscription (e.g. auto-renewing)
        return False
