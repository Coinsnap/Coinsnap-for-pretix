"""Webhook id and secret per Coinsnap store, kept in pretix's global settings so the plugin needs no tables."""
import json
import logging

from django.db import DatabaseError, connection
from pretix.base.settings import GlobalSettingsObject

logger = logging.getLogger(__name__)
LEGACY_TABLE = "coinsnap_coinsnapwebhookstate"


def _key(store_id):
    return f"coinsnap_webhook_{store_id}"


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
