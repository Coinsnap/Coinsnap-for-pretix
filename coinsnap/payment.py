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
from decimal import Decimal
from coinsnap.models import CoinsnapWebhookState, RefCoinsnapObject
from pretix.base.forms import SecretKeySettingsField
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.models import OrderPayment
from pretix.helpers.urls import build_absolute_uri as build_global_uri

logger = logging.getLogger(__name__)


class CoinsnapPayment(BasePaymentProvider):
    identifier = "coinsnap"
    verbose_name = _("Bitcoin-Lightning payment")
    BASE_API_URL = "https://app.coinsnap.io/api/v1/stores"
    COINSNAP_SETTINGS = ["store_id", "api_key"]
    WEBHOOK_EVENTS = ["New", "Expired", "Settled", "Processing"]

    @property
    def settings_form_fields(self):
        fields = super().settings_form_fields
        fields["store_id"] = forms.CharField(
            label="Store Id",
            required=True,
            widget=forms.TextInput(attrs={"placeholder": "Enter store_id"}),
        )
        # Shown redacted; submitting the form unchanged keeps the stored key.
        fields["api_key"] = SecretKeySettingsField(label="Api Key", required=True)
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

    def create_coinsnap_invoice(self, total, currency, redirect, orderID):
        """Creates the invoice and returns the API's answer (id and checkoutLink)."""
        store_id, api_key = self.settings.get("store_id"), self.settings.get("api_key")
        if not currency or not store_id or not api_key:
            raise PaymentException(_("The payment could not be started. Please try again later."))

        payload = {
            "amount": str(Decimal(total).quantize(Decimal("0.01"))),
            "currency": currency,
            "orderId": orderID,
            "redirectUrl": redirect,
            "redirectAutomatically": True,
        }
        try:
            response = requests.post(
                f"{self.BASE_API_URL}/{store_id}/invoices",
                json=payload,
                headers={"x-api-key": api_key},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.error(f"Coinsnap: invoice creation failed for order {orderID} (status {status})")
            raise PaymentException(_("The payment could not be started. Please try again later."))
        if not data.get("id") or not data.get("checkoutLink"):
            logger.error(f"Coinsnap: invoice creation for order {orderID} returned no invoice")
            raise PaymentException(_("The payment could not be started. Please try again later."))
        return data

    def checkout_prepare(self, request, cart):
        """
        Prepare checkout by checking webhook.
        """
        self.register_coinsnap_webhook()
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

    def webhook_url(self):
        # From the configured site URL, never from the request's Host header.
        return build_global_uri("plugins:coinsnap:coinsnap_webhook")

    def register_coinsnap_webhook(self):
        """Makes sure this event's store has our webhook and we hold its secret (one per store, shared by its events)."""
        store_id, api_key = self.settings.get("store_id"), self.settings.get("api_key")
        if not store_id or not api_key:
            return False
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        base = f"{self.BASE_API_URL}/{store_id}/webhooks"
        url = self.webhook_url()
        try:
            state = CoinsnapWebhookState.objects.filter(key=f"store:{store_id}").first()
            webhook_id = state.webhook_id if state else None
            if webhook_id and state.secret:
                response = requests.get(f"{base}/{webhook_id}", headers=headers, timeout=15)
                if response.status_code == 200 and response.json().get("url") == url:
                    return True
                if response.status_code not in (400, 404):
                    # An outage is not a missing webhook; replacing it now would break a working secret.
                    return False

            # Webhooks of ours whose secret we no longer hold (older versions kept one secret for all stores).
            existing = requests.get(base, headers=headers, timeout=15)
            existing.raise_for_status()
            for hook in existing.json() or []:
                if hook.get("url") == url and hook.get("id"):
                    requests.delete(f"{base}/{hook['id']}", headers=headers, timeout=15)

            secret = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            response = requests.post(
                base,
                json={"url": url, "events": self.WEBHOOK_EVENTS, "secret": secret},
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            CoinsnapWebhookState.objects.update_or_create(
                key=f"store:{store_id}",
                defaults={"secret": secret, "webhook_id": response.json().get("id"), "is_connected_to_webhook": True},
            )
            logger.info("Coinsnap: webhook registered")
            return True
        except (requests.exceptions.RequestException, ValueError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.error(f"Coinsnap: webhook could not be registered (status {status})")
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

        invoice = self.create_coinsnap_invoice(
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
            
        # The webhook finds the payment by this invoice id; no other invoice can confirm it.
        payment.info = json.dumps({
            'invoiceId': invoice['id'],
            'amount': str(payment.amount),
            'currency': self.event.currency,
            'redirect': redirect_url,
            'orderID': payment.order.full_code
        })

        payment.save(update_fields=["info"])
        return invoice['checkoutLink']
