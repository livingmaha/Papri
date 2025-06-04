# backend/payments/urls.py
from django.urls import path
from .views import (
    InitializePaystackPaymentView, 
    PaystackCallbackView,
    ListPlansView
)

app_name = 'payments'  # Namespace for this app's URLs

urlpatterns = [
    path('plans/', ListPlansView.as_view(), name='list_plans'),
    path('paystack/initialize/', InitializePaystackPaymentView.as_view(), name='paystack_initialize'),
    
    # This URL name ('paystack_callback') MUST match settings.PAYSTACK_CALLBACK_URL_NAME
    path('paystack/callback/', PaystackCallbackView.as_view(), name='paystack_callback'), 
]
