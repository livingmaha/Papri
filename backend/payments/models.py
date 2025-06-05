# backend/payments/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid

# Import models from other apps if needed for ForeignKey, but be mindful of circular dependencies.
# from api.models import SignupCode # Example, if directly linking

class PaymentTransaction(models.Model):
    """
    Records details of each payment attempt or completed transaction.
    """
    GATEWAY_CHOICES = [
        ('paystack', 'Paystack'),
        ('stripe', 'Stripe'), # Retaining for potential future use
        ('manual', 'Manual/Admin'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending_init', 'Pending Initialization'), # Before redirecting to gateway
        ('initiated', 'Initiated (User at Gateway)'),
        ('successful', 'Successful'),
        ('failed', 'Failed'),
        ('abandoned', 'Abandoned by User'),
        ('error', 'Gateway Error'),
        ('refunded', 'Refunded'),
        ('disputed', 'Disputed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transactions', help_text="User who made/initiated the payment, if authenticated.")
    email_for_guest = models.EmailField(null=True, blank=True, help_text="Email used if payment was by an unauthenticated user.")
    
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount of the transaction.")
    currency = models.CharField(max_length=3, default='USD', help_text="Currency code (e.g., USD, NGN).") # Align with Paystack/settings
    
    payment_gateway = models.CharField(max_length=50, choices=GATEWAY_CHOICES, default='paystack')
    gateway_transaction_id = models.CharField(max_length=255, unique=True, db_index=True, help_text="Unique transaction ID from the payment gateway (e.g., Paystack reference).")
    papri_internal_reference = models.CharField(max_length=255, unique=True, db_index=True, null=True, blank=True, help_text="Papri's internal unique reference for this attempt.")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending_init', db_index=True)
    description = models.CharField(max_length=255, null=True, blank=True, help_text="Short description of the payment (e.g., 'Papri Pro Monthly Subscription').")
    
    # Store raw responses or key details from gateway for auditing/debugging
    gateway_response_data = models.JSONField(null=True, blank=True, help_text="Raw response or key details from the payment gateway.")
    metadata = models.JSONField(null=True, blank=True, help_text="Any additional metadata associated with the transaction (e.g., plan ID, user agent).")

    # If this transaction resulted in a SignupCode (alternative to direct subscription activation)
    # signup_code_generated = models.OneToOneField('api.SignupCode', on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transaction')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True) # Tracks last status update or modification

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"

    def __str__(self):
        user_identifier = self.user.username if self.user else self.email_for_guest or "Guest"
        return f"Txn {self.gateway_transaction_id or self.id} by {user_identifier} for {self.amount} {self.currency} ({self.get_status_display()})"


class Subscription(models.Model):
    """
    Manages user subscriptions to Papri plans.
    """
    PLAN_CHOICES = [
        ('papri_pro_monthly', 'Papri Pro Monthly'),
        ('papri_pro_yearly', 'Papri Pro Yearly'),
        # Add other plans as needed
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled_by_user', 'Cancelled by User'),
        ('cancelled_due_to_payment_failure', 'Cancelled (Payment Failure)'),
        ('pending_activation', 'Pending Activation'), # e.g., after payment, before features unlocked
        ('trial', 'Trial Period'), # Could be a special plan type
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='papri_subscription', help_text="The subscribed user.")
    plan_name = models.CharField(max_length=100, choices=PLAN_CHOICES, help_text="The specific Papri plan subscribed to.")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending_activation', db_index=True)
    
    start_date = models.DateTimeField(help_text="Date and time when the subscription started or will start.")
    end_date = models.DateTimeField(null=True, blank=True, help_text="Date and time when the subscription expires or expired. Null if ongoing indefinitely or managed by gateway.")
    
    # Link to the payment transaction that activated or last renewed this subscription
    activating_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='activated_subscriptions')
    # Gateway specific subscription ID if using gateway's recurring billing features
    gateway_subscription_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Subscription ID from the payment gateway (e.g., Paystack Subscription Code).")
    
    auto_renew = models.BooleanField(default=False, help_text="Does this subscription auto-renew via the payment gateway?")
    cancelled_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp if the subscription was cancelled.")
    
    # Store notes or reasons for status changes, e.g., cancellation reason
    notes = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = "User Subscription"
        verbose_name_plural = "User Subscriptions"

    def __str__(self):
        return f"{self.get_plan_name_display()} for {self.user.username} (Status: {self.get_status_display()})"

    def is_active(self) -> bool:
        """Checks if the subscription is currently active."""
        if self.status == 'active':
            if self.end_date:
                return timezone.now() < self.end_date
            return True # Active and no specific end date (e.g., managed by gateway renewal)
        return False
    
    # You might add methods here to handle activation, cancellation, renewal logic
    # that interacts with UserProfile and possibly payment gateway services.
