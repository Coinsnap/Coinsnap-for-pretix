from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.http import HttpRequest
from django import forms
from django.template.loader import get_template
import requests
import json
import logging
import secrets
import string
import re
from coinsnap.models import CoinsnapWebhookState, RefCoinsnapObject
from pretix.base.payment import BasePaymentProvider
from pretix.base.models import OrderPayment

logger = logging.getLogger(__name__)


class CoinsnapPayment(BasePaymentProvider):
    identifier = "coinsnap"
    verbose_name = _("Bitcoin-Lightning payment")
    BASE_API_URL = "https://app.coinsnap.io/api/v1/stores"
    COINSNAP_SETTINGS = ["store_id", "api_key","custom_domain"]
    WEBHOOK_EVENTS = ["New", "Expired", "Settled", "Processing"]

    @property
    def settings_form_fields(self):
        fields = super().settings_form_fields
        for setting in self.COINSNAP_SETTINGS:
            fields[setting] = forms.CharField(
                label=setting.replace("_", " ").title(),
                required=True,
                widget=forms.TextInput(attrs={"placeholder": f"Enter {setting}"}),
            )
        return fields

    
    def settings_form_clean(self, cleaned_data):
        """
        Validate that store ID and API do exist.
        """

        cleaned_data = super().settings_form_clean(cleaned_data)

        store_id = cleaned_data.get("payment_coinsnap_store_id")
        api_key = cleaned_data.get("payment_coinsnap_api_key")
        if len(store_id) <= 0:
            raise forms.ValidationError("Store ID must not be empty!")
        if len(api_key) <= 0:
            raise forms.ValidationError("API Key must not be empty!")
        
        return cleaned_data

    def is_available(self) -> bool:
        return True

    def payment_is_valid_session(self, request):
        return True

    def create_coinsnap_invoice(self, request, total, currency, redirect, orderID):
        """
        Create an invoice with Coinsnap API.
        
        Args:
            request: Django request object
            total: Payment amount
            currency: Payment currency
            redirect: Redirect URL after payment
            orderID: Unique order identifier
        
        Returns:
            bool: Whether invoice creation was successful
        """

        store_id, api_key = self.settings.get("store_id"), self.settings.get("api_key")

        if not currency:
            raise ValueError("Currency could not be determined from the cart.")

        if not store_id or not api_key:
            raise ValueError(
                "Store ID and API Key must be configured in the plugin settings."
            )
        url = f"{self.BASE_API_URL}/{store_id}/invoices"
        headers = {"x-api-key": api_key}
        payload = {
            "amount": float(total),
            "currency": currency,
            "orderId": orderID,
            "redirectUrl": redirect,
            "redirectAutomatically": True,
        }
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            logger.info(f"Invoice created with checkout link: {data.get('checkoutLink')}")
            request.session["coinsnap_checkout_link"] = data.get("checkoutLink")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating Coinsnap invoice: {e}")
            raise

    def checkout_prepare(self, request, cart):
        """
        Prepare checkout by checking webhook.
        """
        domain = f'{request.scheme}://{request.get_host()}'
        self.register_coinsnap_webhook(domain=domain)
        return True

    def payment_form_render(self, request) -> str:
        """
        Render payment form template.
        """
        template = get_template("coinsnap/checkout_payment_form.html")
        ctx = {"request": request, "event": self.event, "settings": self.settings}
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        """
        Render checkout confirmation template.
        """
        template = get_template("coinsnap/checkout_payment_confirm.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
        }
        return template.render(ctx)

    def register_coinsnap_webhook(self, force=False, domain=None):
        """
        Registers a webhook with Coinsnap to listen for payment events.

        Args:
            force: Force re-registration of webhook
        
        Returns:
            bool: Whether webhook registration was successful

        """
        store_id, api_key, custom_domain = self.settings.get("store_id"), self.settings.get("api_key"), self.settings.get("custom_domain")
        domain = custom_domain or domain

        CoinsnapWebhookState.objects.get_or_create(key='webhook_connection', defaults={'is_connected_to_webhook': False})
        
        if force:
            CoinsnapWebhookState.set(False)

        if CoinsnapWebhookState.get():
            return True
        
        characters = string.ascii_letters + string.digits
        secret = ''.join(secrets.choice(characters) for _ in range(32))

        url = f"{self.BASE_API_URL}/{store_id}/webhooks"
        payload = {
            "url": f'{domain}/pretix/webhooks/coinsnap',
            "events": self.WEBHOOK_EVENTS,
            "secret": secret,
        }
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            CoinsnapWebhookState.set_secret(secret)

            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info("Webhook registered successfully.")

            CoinsnapWebhookState.set(True)
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to register webhook: {e}")
            CoinsnapWebhookState.set(False)
            return False


    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        """
        Execute payment by creating a Coinsnap invoice and returning checkout link.

        Returns:
            str: Coinsnap checkout link
        """
        # Construct the full redirect URL
        redirect_url = request.build_absolute_uri(
            reverse(
                "presale:event.order",
                kwargs={
                    "event": self.event.slug,
                    "organizer": self.event.organizer.slug,
                    "order": payment.order.code,
                    "secret": payment.order.secret,
                },
            )
        )
        custom_domain = self.settings.get("custom_domain")
        if(custom_domain):
            redirect_url = re.sub(r'https?://[^/]+', custom_domain, redirect_url)

        self.create_coinsnap_invoice(
            request,
            payment.amount,
            self.event.currency,
            redirect=redirect_url,
            orderID=payment.order.full_code,
        )

        existing_ref_obj = RefCoinsnapObject.objects.filter(
            reference=payment.order.full_code
        ).first()

        if not existing_ref_obj:
            existing_ref_obj = RefCoinsnapObject.objects.create(
                order=payment.order, 
                payment=payment, 
                reference=payment.order.full_code
            )
            
        payment.info = json.dumps({
            'amount' : float(payment.amount),
            'currency': self.event.currency,
            'redirect': redirect_url,
            'orderID': payment.order.full_code
        })

        payment.save(update_fields=["info"])
        return request.session["coinsnap_checkout_link"]
