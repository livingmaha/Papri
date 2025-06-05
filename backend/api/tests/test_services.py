# backend/payments/tests/test_services.py
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch, MagicMock
import hmac
import hashlib

from payments.services import PaystackService
from api.models import SignupCode, UserProfile # Assuming these are in 'api'
from payments.models import PaymentTransaction, Subscription

class PaystackServiceTests(TestCase):
    """Test suite for the PaystackService."""

    def setUp(self):
        self.user = User.objects.create_user(username='payuser', email='payuser@example.com', password='password123')
        self.paystack_service = PaystackService()
        # Ensure UserProfile is created for self.user
        UserProfile.objects.get_or_create(user=self.user)


    @override_settings(PAYSTACK_SECRET_KEY='test_sk_valid', PAYSTACK_WEBHOOK_SECRET='test_wh_secret')
    @patch('requests.post')
    def test_initialize_transaction_success(self, mock_post):
        """Test successful transaction initialization."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True,
            "message": "Authorization URL created",
            "data": {
                "authorization_url": "[http://paystack.example.com/auth/123](http://paystack.example.com/auth/123)",
                "access_code": "access_code_123",
                "reference": "ref_123xyz"
            }
        }
        mock_post.return_value = mock_response

        result = self.paystack_service.initialize_transaction(
            amount_kobo=500000, # 5000 NGN
            email="customer@example.com",
            callback_url="[http://example.com/callback](http://example.com/callback)",
            reference="ref_123xyz"
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['reference'], "ref_123xyz")
        mock_post.assert_called_once()

    @override_settings(PAYSTACK_SECRET_KEY='test_sk_valid')
    @patch('requests.get')
    def test_verify_transaction_success(self, mock_get):
        """Test successful transaction verification."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": True, "message": "Verification successful",
            "data": { "status": "success", "reference": "ref_verified", "amount": 500000, "customer": {"email": "customer@example.com"}}
        }
        mock_get.return_value = mock_response

        result = self.paystack_service.verify_transaction(reference="ref_verified")
        self.assertTrue(result['success'])
        self.assertEqual(result['data']['status'], 'success')

    @override_settings(PAYSTACK_SECRET_KEY='test_sk_valid')
    def test_handle_successful_payment_for_signup_code(self):
        """Test logic for creating a SignupCode after successful payment."""
        email = "new_user@example.com"
        plan_name = "Papri Pro Monthly Test"
        payment_reference = "test_ref_signup"
        transaction_data = {"status": "success", "reference": payment_reference, "customer": {"email": email}, "amount": 60000} # 600 USD in kobo/cents

        success, message = self.paystack_service.handle_successful_payment_for_signup_code(
            email, plan_name, payment_reference, transaction_data
        )
        self.assertTrue(success)
        self.assertTrue(SignupCode.objects.filter(email=email, payment_reference=payment_reference).exists())
        signup_code = SignupCode.objects.get(email=email, payment_reference=payment_reference)
        self.assertEqual(signup_code.plan_name, plan_name)

    @override_settings(PAYSTACK_WEBHOOK_SECRET='test_webhook_secret_key_123')
    def test_verify_webhook_signature_valid(self):
        """Test valid webhook signature verification."""
        payload_body = b'{"event":"charge.success","data":{}}'
        correct_signature = hmac.new(
            b'test_webhook_secret_key_123',
            payload_body,
            hashlib.sha512
        ).hexdigest()
        
        self.assertTrue(self.paystack_service.verify_webhook_signature(payload_body, correct_signature))

    @override_settings(PAYSTACK_WEBHOOK_SECRET='test_webhook_secret_key_123')
    def test_verify_webhook_signature_invalid(self):
        """Test invalid webhook signature verification."""
        payload_body = b'{"event":"charge.success","data":{}}'
        incorrect_signature = "thisisclearlywrong"
        self.assertFalse(self.paystack_service.verify_webhook_signature(payload_body, incorrect_signature))

    @override_settings(PAYSTACK_WEBHOOK_SECRET='test_webhook_secret_key_123')
    @patch.object(User.objects, 'get_or_create') # Mock User.get_or_create
    def test_handle_webhook_event_charge_success(self, mock_get_or_create_user):
        """Test handling of a 'charge.success' webhook event."""
        mock_user_instance = self.user
        mock_get_or_create_user.return_value = (mock_user_instance, True) # Simulate user creation

        event_type = "charge.success"
        event_data = {
            "reference": "webhook_ref_charge_success",
            "status": "success",
            "amount": 60000, # USD 600 in kobo
            "currency": "USD",
            "customer": {"email": "webhook_user@example.com", "customer_code": "CUS_123"},
            "metadata": {"papri_plan_name": "Papri Pro Yearly Hook"},
            # ... other fields Paystack sends
        }
        # Ensure a PaymentTransaction exists to be updated by the webhook
        PaymentTransaction.objects.create(
            gateway_transaction_id=event_data['reference'],
            email_for_guest=event_data['customer']['email'],
            amount=Decimal(event_data['amount'])/100,
            currency=event_data['currency'],
            status='initiated' # Initial status before webhook
        )

        success, message = self.paystack_service.handle_webhook_event(event_type, event_data)
        
        self.assertTrue(success)
        self.assertTrue("Charge successful, user profile and signup code processed" in message)
        
        # Verify UserProfile updated
        user_profile = UserProfile.objects.get(user__email="webhook_user@example.com")
        self.assertEqual(user_profile.subscription_plan, "papri_pro_yearly_hook") # Matches metadata
        
        # Verify SignupCode created
        self.assertTrue(SignupCode.objects.filter(email="webhook_user@example.com", payment_reference=event_data['reference']).exists())
        
        # Verify PaymentTransaction status updated
        txn = PaymentTransaction.objects.get(gateway_transaction_id=event_data['reference'])
        self.assertEqual(txn.status, 'webhook_processed_ok')


    @override_settings(PAYSTACK_WEBHOOK_SECRET='test_wh_secret')
    @patch.object(User.objects, 'get_or_create')
    def test_handle_webhook_event_subscription_create(self, mock_get_or_create_user):
        """Test handling of 'subscription.create' webhook event."""
        mock_user_instance = self.user
        mock_get_or_create_user.return_value = (mock_user_instance, True)

        event_type = "subscription.create"
        event_data = {
            "subscription_code": "SUB_abc123xyz",
            "customer": {"email": self.user.email, "customer_code": "CUS_test123"},
            "plan": {"name": "Papri Monthly Plan via API", "plan_code": "PLN_monthly"},
            "amount": 60000, # 600 USD in cents
            "status": "active",
            "next_payment_date": (timezone.now() + timezone.timedelta(days=30)).isoformat(),
            # ... other fields Paystack sends for subscription.create
        }
        PaymentTransaction.objects.create(gateway_transaction_id='some_txn_for_sub_init', amount=0, currency='USD', status='initiated') # Dummy txn

        success, message = self.paystack_service.handle_webhook_event(event_type, event_data)
        self.assertTrue(success)
        self.assertTrue(Subscription.objects.filter(gateway_subscription_code="SUB_abc123xyz", user=self.user).exists())
        
        sub = Subscription.objects.get(gateway_subscription_code="SUB_abc123xyz")
        self.assertEqual(sub.status, "active")
        
        user_profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(user_profile.subscription_plan, "papri_pro_monthly") # Based on default mapping
        self.assertEqual(user_profile.subscription_id_gateway, "SUB_abc123xyz")
