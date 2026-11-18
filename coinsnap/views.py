import json
import logging
import re
import time

import requests
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_scopes import scope, scopes_disabled
from pretix.base.models import OrderPayment, Quota

from coinsnap import store_webhooks, webhook

logger = logging.getLogger(__name__)
API_URL = "https://app.coinsnap.io/api/v1/stores"

# A payment that has not been paid yet, or one pretix cancelled (e.g. the customer started another attempt): a real
# late payment is still recorded. Confirmed and refunded payments never change from a webhook.
CONFIRMABLE = (
    OrderPayment.PAYMENT_STATE_CREATED,
    OrderPayment.PAYMENT_STATE_PENDING,
    OrderPayment.PAYMENT_STATE_CANCELED,
    OrderPayment.PAYMENT_STATE_FAILED,
)


_local_count = [0, 0]


def _log(level, reason, invoice_id):
    line = f"Coinsnap {level} webhook reason={reason} invoice={invoice_id or '-'}"
    if level != "SECURITY":
        logger.info(line)
        return
    # At most 10 security lines a minute, so a flood of fake requests can't fill the log.
    minute = int(time.time() // 60)
    key = f"coinsnap_seclog_{minute}"
    try:
        cache.add(key, 0, 120)
        count = cache.incr(key)
    except ValueError:
        # pretix's default cache (no redis or memcached) stores nothing; count in this process instead.
        if _local_count[0] != minute:
            _local_count[:] = [minute, 0]
        _local_count[1] += 1
        count = _local_count[1]
    if count == 11:
        logger.warning("Coinsnap SECURITY webhook: more rejections this minute, not logged")
    if count <= 10:
        logger.warning(line)


def _secrets():
    with scopes_disabled():
        pairs = store_webhooks.all_secrets()
        legacy = store_webhooks.legacy_secret()
    if legacy:
        pairs.append((webhook.LEGACY, legacy))
    return pairs


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
        with scope(organizer=payment.order.event.organizer), transaction.atomic():
            # Locked, so a refund or a second webhook arriving at the same moment is seen here.
            locked = OrderPayment.objects.select_for_update().get(pk=payment.pk)
            if locked.state == OrderPayment.PAYMENT_STATE_CONFIRMED:
                return "already processed"
            if locked.state not in CONFIRMABLE:
                return f"no change: payment {locked.state}"
            try:
                locked.confirm()
            except Quota.QuotaExceededException:
                # The payment is recorded; pretix leaves the order for the organizer to resolve.
                logger.warning(f"Coinsnap: order {payment.order.full_code} is paid but its quota is exhausted")
            return "paid"

    return confirm


def _candidate(payment, record):
    return {
        "order_code": payment.order.full_code,
        "amount": record["amount"],
        "currency": record["currency"],
        "fetch": _fetcher(payment.payment_provider.settings),
        "confirm": _confirmer(payment),
    }


def _store_of(payment):
    return payment.payment_provider.settings.get("store_id") or ""


def _candidates_for(invoice_id, data, source):
    with scopes_disabled():
        related = ("order", "order__event", "order__event__organizer")
        # The invoice id is checked against the payment's own records below; this only narrows the search.
        payments = OrderPayment.objects.filter(provider="coinsnap", info__contains=f'"{invoice_id}"').select_related(*related)
        candidates = []
        for payment in payments:
            record = store_webhooks.invoice_record(payment, invoice_id)
            # Only the store that created the invoice can vouch for it.
            if record and source != webhook.LEGACY and _store_of(payment) == source:
                candidates.append(_candidate(payment, record))
        if candidates:
            return candidates

        # Payments created before 0.2.0 carry no invoice id; the order code in their info is the only link.
        # They are accepted only for a day after the upgrade, when every invoice opened before it has expired.
        if not store_webhooks.legacy_window_open():
            return []
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        order_code = metadata.get("orderId")
        if not isinstance(order_code, str) or not re.match(r"^[A-Za-z0-9_-]{1,190}$", order_code):
            return []
        payments = OrderPayment.objects.filter(
            provider="coinsnap",
            info__contains=f'"orderID": "{order_code}"',
            state__in=(OrderPayment.PAYMENT_STATE_CREATED, OrderPayment.PAYMENT_STATE_PENDING),
        ).select_related(*related)
        for payment in payments:
            try:
                info = json.loads(payment.info or "{}")
            except ValueError:
                continue
            if not isinstance(info, dict) or info.get("invoiceId") or info.get("invoices"):
                continue
            # Webhooks registered before the upgrade carry the old shared secret; after it, the store's own.
            if source == webhook.LEGACY or _store_of(payment) == source:
                record = {"amount": str(payment.amount), "currency": payment.order.event.currency}
                candidates.append(_candidate(payment, record))
        return candidates


@csrf_exempt
@require_POST
def coinsnap_webhook(request):
    status = webhook.process(
        request.body,
        request.headers.get("X-Coinsnap-Signature", ""),
        _secrets,
        _candidates_for,
        _log,
    )
    text = {200: "OK", 401: "Unauthorized"}.get(status, "Retry")
    return HttpResponse(text, status=status, content_type="text/plain")
