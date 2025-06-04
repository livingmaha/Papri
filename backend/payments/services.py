# backend/payments/services.py
import requests
import os
import json
import logging
from django.conf import settings # To get Paystack keys and base URL

logger = logging.getLogger(__name__)

class PaystackService:
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.public_key = settings.PAYSTACK_PUBLIC_KEY # May not be used much in backend
        self.base_url = "https://api.paystack.co" # Paystack API base URL

        if not self.secret_key:
            logger.critical("PAYSTACK_SECRET_KEY is not set in Django settings!")
            # Depending on your app's needs, you might raise an error here
            # or allow the service to be instantiated but fail on API calls.

    def _get_headers(self):
        if not self.secret_key:
            raise ValueError("Paystack secret key is not configured.")
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }

    def initialize_transaction(self, amount_kobo: int, email: str, callback_url: str, reference: str = None, metadata: dict = None, currency: str = "NGN"):
        """
        Initializes a Paystack transaction.
        Args:
            amount_kobo (int): Amount in kobo (e.g., 10000 for NGN 100.00). Paystack expects this as an integer.
            email (str): User's email.
            callback_url (str): URL Paystack redirects to after payment attempt.
            reference (str, optional): Unique transaction reference from your system. If not provided, Paystack generates one.
            metadata (dict, optional): Custom data (JSON serializable) to associate with the transaction.
                                       Example: {"custom_fields": [{"display_name": "Order ID", "variable_name": "order_id", "value": "123"}]}
            currency (str, optional): Currency code (e.g., "NGN", "USD", "GHS"). Defaults to "NGN".
        Returns:
            dict: Contains Paystack's response or an error structure.
                  On success: {"success": True, "authorization_url": "...", "access_code": "...", "reference": "..."}
                  On failure: {"success": False, "error": "Error message"}
        """
        url = f"{self.base_url}/transaction/initialize"
        
        payload = {
            "email": email,
            "amount": str(amount_kobo), # Paystack API expects amount as string for kobo/cents
            "currency": currency,
            "callback_url": callback_url,
        }
        if reference:
            payload["reference"] = reference
        if metadata:
            payload["metadata"] = json.dumps(metadata) # Paystack expects metadata as a JSON string

        logger.debug(f"Paystack initialize transaction payload: {payload}")

        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=20) # Increased timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            data = response.json()
            logger.debug(f"Paystack initialize response data: {data}")

            if data.get("status") is True:
                return {
                    "success": True,
                    "authorization_url": data["data"]["authorization_url"],
                    "access_code": data["data"]["access_code"],
                    "reference": data["data"]["reference"], # Paystack's generated reference or yours if passed
                }
            else:
                error_msg = data.get("message", "Paystack initialization failed without specific message.")
                logger.error(f"Paystack initialization logical error: {error_msg}. Response: {data}")
                return {"success": False, "error": error_msg}
        except requests.exceptions.HTTPError as http_err:
            error_content = http_err.response.text
            logger.error(f"Paystack API HTTP error (initialize): {http_err}. Response body: {error_content}", exc_info=True)
            return {"success": False, "error": f"Paystack API error: {str(http_err)}. Details: {error_content[:200]}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API request network error (initialize): {e}", exc_info=True)
            return {"success": False, "error": f"Network error communicating with Paystack: {str(e)}"}
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"Unexpected error initializing Paystack transaction: {e}", exc_info=True)
            return {"success": False, "error": f"An unexpected error occurred: {str(e)}"}

    def verify_transaction(self, reference: str):
        """
        Verifies a Paystack transaction status using its reference.
        Args:
            reference (str): The transaction reference provided by Paystack or your system.
        Returns:
            dict: Contains transaction details or an error structure.
                  On successful verification of a completed payment: {"success": True, "message": "...", "data": {...transaction_data...}}
                  On failure or if payment not successful: {"success": False, "error": "...", "data": {...partial_data_if_any...}}
        """
        if not reference:
            return {"success": False, "error": "Transaction reference cannot be empty."}
            
        url = f"{self.base_url}/transaction/verify/{reference}"
        logger.debug(f"Verifying Paystack transaction with reference: {reference}")

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=15)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Paystack verify response data for ref '{reference}': {data}")

            if data.get("status") is True: # API call itself was successful
                transaction_status = data["data"].get("status")
                if transaction_status == "success":
                    # Transaction is successful, access details in data["data"]
                    # e.g., data["data"]["amount"], data["data"]["customer"]["email"], data["data"]["metadata"]
                    return {
                        "success": True,
                        "message": "Transaction verified successfully and payment was successful.",
                        "data": data["data"] # Includes status, amount, customer info, metadata etc.
                    }
                else:
                    # Transaction status is not "success" (e.g., "failed", "abandoned")
                    logger.warning(f"Paystack verification: Transaction '{reference}' not successful. Status: {transaction_status}. Gateway response: {data['data'].get('gateway_response')}")
                    return {
                        "success": False, 
                        "error": f"Payment not successful. Status: {transaction_status}. Gateway Message: {data['data'].get('gateway_response', 'N/A')}",
                        "data": data["data"] # Return data even for non-successful payments for logging/info
                    }
            else:
                # API call status is False
                error_msg = data.get("message", f"Paystack verification failed for '{reference}' without specific message.")
                logger.error(f"Paystack verification API error for '{reference}': {error_msg}. Response: {data}")
                return {"success": False, "error": error_msg}
        except requests.exceptions.HTTPError as http_err:
            error_content = http_err.response.text
            # Paystack might return 404 if reference is invalid
            if http_err.response.status_code == 404:
                 logger.warning(f"Paystack verify: Transaction reference '{reference}' not found (404).")
                 return {"success": False, "error": f"Transaction reference '{reference}' not found."}
            logger.error(f"Paystack API HTTP error (verify ref '{reference}'): {http_err}. Response body: {error_content}", exc_info=True)
            return {"success": False, "error": f"Paystack API error: {str(http_err)}. Details: {error_content[:200]}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Paystack API request network error (verify ref '{reference}'): {e}", exc_info=True)
            return {"success": False, "error": f"Network error communicating with Paystack: {str(e)}"}
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"Unexpected error verifying Paystack transaction '{reference}': {e}", exc_info=True)
            return {"success": False, "error": f"An unexpected error occurred: {str(e)}"}

    # You can add other Paystack API methods here as needed, e.g.:
    # - list_transactions
    # - fetch_transaction
    # - charge_authorization (for recurring payments if you store authorization codes)
    # - manage_subscriptions (if using Paystack's subscription plans)
