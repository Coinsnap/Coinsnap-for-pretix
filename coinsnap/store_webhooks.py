"""Webhook id and secret per Coinsnap store, kept in pretix's global settings so the plugin needs no tables."""
import json
import logging
import time

from django.db import DatabaseError, connection
from pretix.base.settings import GlobalSettingsObject

PREFIX = "coinsnap_webhook_"
# When this version first ran; payments from earlier versions are accepted for a day after it.
UPGRADED_AT = "coinsnap_invoice_records_since"
LEGACY_WINDOW_SECONDS = 24 * 3600

logger = logging.getLogger(__name__)
LEGACY_TABLE = "coinsnap_coinsnapwebhookstate"


def _key(store_id):
    return f"{PREFIX}{store_id}"


def get(store_id):
    """{"secret": ..., "webhook_id": ...} for the store, or an empty dict."""
    if not store_id:
        return {}
    try:
        data = json.loads(GlobalSettingsObject().settings.get(_key(store_id)) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(store_id, secret, webhook_id):
    GlobalSettingsObject().settings.set(_key(store_id), json.dumps({"secret": secret, "webhook_id": webhook_id}))


def all_secrets():
    """(store id, secret) for every store this instance registered a webhook on."""
    from pretix.base.models import GlobalSettingsObject_SettingsStore

    pairs = []
    for key, value in GlobalSettingsObject_SettingsStore.objects.filter(key__startswith=PREFIX).values_list("key", "value"):
        try:
            data = json.loads(value or "{}")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("secret"):
            pairs.append((key[len(PREFIX):], data["secret"]))
    return pairs


def upgraded_at():
    """Unix time this version first ran, recorded on the first call."""
    settings = GlobalSettingsObject().settings
    try:
        value = int(settings.get(UPGRADED_AT) or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        value = int(time.time())
        settings.set(UPGRADED_AT, str(value))
    return value


def legacy_window_open(now_seconds=None):
    now_seconds = int(time.time()) if now_seconds is None else now_seconds
    return now_seconds - upgraded_at() <= LEGACY_WINDOW_SECONDS


def invoice_records(info):
    """Every invoice created for a payment, each with the amount and currency it asked for."""
    if not isinstance(info, dict):
        return []
    records = [r for r in info.get("invoices") or [] if isinstance(r, dict) and r.get("id")]
    if not records and info.get("invoiceId"):
        # Written by 0.2.0 before every invoice was kept.
        records = [{"id": info["invoiceId"], "amount": info.get("amount"), "currency": info.get("currency")}]
    return records


def invoice_record(payment, invoice_id):
    try:
        info = json.loads(payment.info or "{}")
    except ValueError:
        return None
    for record in invoice_records(info):
        if record["id"] == invoice_id and record.get("amount") and record.get("currency"):
            return record
    return None


def legacy_secret():
    """The one secret versions before 0.2.0 kept for all stores, if that table exists on this install."""
    try:
        if LEGACY_TABLE not in connection.introspection.table_names():
            return None
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT secret FROM {LEGACY_TABLE} WHERE {connection.ops.quote_name('key')} = %s",
                ["webhook_connection"],
            )
            row = cursor.fetchone()
    except DatabaseError:
        logger.warning("Coinsnap: the legacy webhook secret could not be read")
        return None
    return row[0] if row and row[0] else None
