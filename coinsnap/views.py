import json
import logging
import time

import requests
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_scopes import scope, scopes_disabled
from pretix.base.models import OrderPayment, Quota

from coinsnap import webhook
from coinsnap.models import CoinsnapWebhookState, RefCoinsnapObject

logger = logging.getLogger(__name__)
API_URL = "https://app.coinsnap.io/api/v1/stores"


def _log(level, reason, invoice_id):
    line = f"Coinsnap {level} webhook reason={reason} invoice={invoice_id or '-'}"
    if level != "SECURITY":
        logger.info(line)
        return
    # At most 10 security lines a minute, so a flood of fake requests can't fill the log.
    key = f"coinsnap_seclog_{int(time.time() // 60)}"
    cache.add(key, 0, 120)
    count = cache.incr(key)
    if count == 11:
        logger.warning("Coinsnap SECURITY webhook: more rejections this minute, not logged")
    if count <= 10:
        logger.warning(line)


def _fetcher(settings):
    def fetch(invoice_id):
        response = requests.get(
            f"{API_URL}/{settings.get('store_id')}/invoices/{invoice_id}",
            headers={"x-api-key": settings.get("api_key")},
            timeout=15,
        )
        if response.status_code != 200:
            raise webhook.ApiError(response.status_code)
        return response.json()

    return fetch


def _confirmer(payment):
    def confirm():
        with scope(organizer=payment.order.event.organizer):
            try:
                payment.confirm()
            except Quota.QuotaExceededException:
                # The payment is recorded; pretix leaves the order for the organizer to resolve.
                logger.warning(f"Coinsnap: order {payment.order.full_code} is paid but its quota is exhausted")

    return confirm


def _candidate(payment, secret):
    settings = payment.payment_provider.settings
    try:
        info = json.loads(payment.info or "{}")
    except ValueError:
        info = {}
    return {
        "secret": secret or "",
        "order_code": payment.order.full_code,
        "invoice_id": info.get("invoiceId"),
        "amount": str(payment.amount),
        "currency": payment.order.event.currency,
        "confirmed": payment.state == OrderPayment.PAYMENT_STATE_CONFIRMED,
        "fetch": _fetcher(settings),
        "confirm": _confirmer(payment),
    }


def _candidates_for(invoice_id, data):
    with scopes_disabled():
        payments = list(
            OrderPayment.objects.filter(provider="coinsnap", info__contains=f'"invoiceId": "{invoice_id}"')
            .select_related("order", "order__event", "order__event__organizer")
        )
        if not payments:
            # Payments created before 0.2.0 carry no invoice id; their order code is the only link.
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            order_code = metadata.get("orderId")
            if isinstance(order_code, str) and order_code:
                ref = RefCoinsnapObject.objects.filter(reference=order_code).select_related(
                    "payment", "payment__order", "payment__order__event"
                ).first()
                if ref and ref.payment and ref.payment.provider == "coinsnap":
                    payments = [ref.payment]

        candidates = []
        legacy_secret = CoinsnapWebhookState.get_secret()
        for payment in payments:
            store_id = payment.payment_provider.settings.get("store_id")
            state = CoinsnapWebhookState.objects.filter(key=f"store:{store_id}").first()
            store_secret = state.secret if state else None
            for secret in {store_secret, legacy_secret} - {None, ""}:
                candidates.append(_candidate(payment, secret))
        return candidates


@csrf_exempt
@require_POST
def coinsnap_webhook(request):
    status = webhook.process(
        request.body,
        request.headers.get("X-Coinsnap-Signature", ""),
        _candidates_for,
        _log,
    )
    text = {200: "OK", 401: "Unauthorized"}.get(status, "Retry")
    return HttpResponse(text, status=status, content_type="text/plain")
