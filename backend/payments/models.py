# backend/payments/models.py
# from django.db import models
# from django.contrib.auth.models import User
# from django.utils import timezone
# import uuid

# class PaymentTransaction(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
#     email = models.EmailField(null=True, blank=True) # For unauthenticated payments
#     amount = models.DecimalField(max_digits=10, decimal_places=2)
#     currency = models.CharField(max_length=3) # e.g., NGN, USD, GHS
#     payment_gateway = models.CharField(max_length=50, default='paystack')
#     gateway_reference = models.CharField(max_length=255, unique=True, db_index=True)
#     papri_internal_reference = models.CharField(max_length=255, unique=True, db_index=True) # Your system's ref
#     status_choices = [('pending', 'Pending'), ('successful', 'Successful'), ('failed', 'Failed'), ('abandoned', 'Abandoned')]
#     status = models.CharField(max_length=20, choices=status_choices, default='pending')
#     metadata_json = models.JSONField(null=True, blank=True, help_text="Raw response or extra data from gateway")
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     def __str__(self):
#         return f"Payment {self.gateway_reference} via {self.payment_gateway} for {self.amount} {self.currency} ({self.status})"

# class Subscription(models.Model):
#     user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription_details')
#     plan_name = models.CharField(max_length=100) # e.g., Papri Pro Monthly
#     start_date = models.DateTimeField()
#     end_date = models.DateTimeField()
#     is_active = models.BooleanField(default=True)
#     auto_renew = models.BooleanField(default=False)
#     last_payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     def __str__(self):
#         return f"{self.plan_name} for {self.user.username} (Active: {self.is_active})"

# For now, this file can be nearly empty if `SignupCode` is sufficient.
# If you add models here, remember to create an `admin.py` and migrations.
