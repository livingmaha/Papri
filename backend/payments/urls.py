# backend/payments/urls.py
from django.urls import path
from .views import (
    InitializePaystackPaymentView,
    PaystackCallbackView,
    ListPlansView,
    PaystackWebhookView # ADDED
)

app_name = 'payments'

urlpatterns = [
    path('plans/', ListPlansView.as_view(), name='list_plans'),
    path('paystack/initialize/', InitializePaystackPaymentView.as_view(), name='paystack_initialize'),
    path('paystack/callback/', PaystackCallbackView.as_view(), name='paystack_callback'),
    
    # ADDED: URL for Paystack Webhook notifications
    path('paystack/webhook/', PaystackWebhookView.as_view(), name='paystack_webhook'),
]
