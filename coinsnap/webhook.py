"""Webhook rules, kept free of Django so they can be tested on their own.

Only the invoice id is taken from the request; whether a payment is confirmed is
decided from the invoice as the Coinsnap API reports it.
"""
import hashlib
import hmac
import json
import re
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAID = "paid"
PROCESSING = "processing"
EXPIRED = "expired"
NONE = "none"
# Settled, but not for the amount and currency this plugin asked for.
MISMATCH = "mismatch"

MAX_AGE_SECONDS = 300
_INVOICE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ApiError(Exception):
    def __init__(self, status):
        super().__init__(f"Coinsnap API answered {status}")
        self.status = status


def signature_problem(header, body, secret, now_seconds):
    """X-Coinsnap-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "t.body">. None when valid."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    try:
        timestamp = int(parts.get("t", "0"))
    except ValueError:
        timestamp = 0
    signature = parts.get("v1", "")
    if not secret or timestamp <= 0 or not signature:
        return "bad signature"
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return "bad signature"
    if abs(now_seconds - timestamp) > MAX_AGE_SECONDS:
        return "stale timestamp"
    return None


def to_minor_units(value):
    """Amount as an integer of 10^-8 units, never compared as a float."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int((amount * 100_000_000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def decide(invoice, expected_amount, expected_currency):
    status = str(invoice.get("status") or "")
    if status == "Settled":
        paid = invoice.get("invoiceAmount")
        if paid in (None, ""):
            paid = invoice.get("fiatAmount")
        paid = to_minor_units(paid) if paid not in (None, "") else None
        expected = to_minor_units(expected_amount)
        same_currency = str(invoice.get("currency") or "").upper() == str(expected_currency).upper()
        # One unit of the 8th decimal covers rounding for BTC; a cent otherwise.
        tolerance = 1 if str(expected_currency).upper() == "BTC" else 1_000_000
        ok = paid is not None and expected and same_currency and abs(paid - expected) <= tolerance
        return PAID if ok else MISMATCH
    return {"Processing": PROCESSING, "Expired": EXPIRED}.get(status, NONE)


def invoice_id_from_body(body):
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    invoice_id = data.get("invoiceId")
    if not isinstance(invoice_id, str) or not _INVOICE_ID.match(invoice_id):
        return "", data
    return invoice_id, data


LEGACY = "legacy"


def verified_source(header, body, secrets, now_seconds):
    """(source, None) for the first (source, secret) pair whose secret signed the body, else (None, problem)."""
    problem = "bad signature"
    for source, secret in secrets:
        found = signature_problem(header, body, secret, now_seconds)
        if found is None:
            return source, None
        if found == "stale timestamp":
            problem = found
    return None, problem


def process(body, signature_header, secrets, candidates_for, log, now_seconds=None):
    """Returns the HTTP status for the reply.

    secrets() gives (source, secret) pairs: one per Coinsnap store we registered a webhook on (source = that
    store), plus LEGACY for the one secret versions before 0.2.0 shared between all stores. The signature is
    checked against them before the body is read.

    candidates_for(invoice_id, data, source) gives the payments this webhook may be about, each a dict with
    order_code, amount, currency (what that invoice asked for), fetch(invoice_id) -> invoice dict (raises
    ApiError) and confirm() -> "paid" or the reason nothing changed.
    """
    now_seconds = int(time.time()) if now_seconds is None else now_seconds
    source, problem = verified_source(signature_header, body, secrets(), now_seconds)
    if source is None:
        log("SECURITY", problem, "")
        return 401

    invoice_id, data = invoice_id_from_body(body)
    if not invoice_id:
        return 200

    candidates = candidates_for(invoice_id, data, source)
    if not candidates:
        # The dashboard's "Send test webhook" button lands here.
        log("INFO", "not ours", invoice_id)
        return 200

    # All candidates belong to one order of one event, so one store answers for them.
    try:
        invoice = candidates[0]["fetch"](invoice_id)
    except ApiError as e:
        if e.status in (400, 404):
            log("INFO", "unknown invoice", invoice_id)
            return 200
        log("INFO", "retry: API unavailable", invoice_id)
        return 503
    except Exception:
        log("INFO", "retry: API unavailable", invoice_id)
        return 503
    if not isinstance(invoice, dict):
        log("INFO", "retry: API unavailable", invoice_id)
        return 503

    claims_paid = data.get("type") == "Settled"
    candidates = [c for c in candidates if str(invoice.get("orderId") or "") == c["order_code"]]
    if not candidates:
        log("SECURITY" if claims_paid else "INFO", "invoice of another order", invoice_id)
        return 200

    decisions = [(decide(invoice, c["amount"], c["currency"]), c) for c in candidates]
    payment = next((c for d, c in decisions if d == PAID), None)
    if payment is None:
        mismatch = any(d == MISMATCH for d, _ in decisions)
        if claims_paid or mismatch:
            log("SECURITY", "forged status" if claims_paid else "amount mismatch", invoice_id)
        else:
            log("INFO", f"status {decisions[0][0]}", invoice_id)
        return 200

    log("INFO", payment["confirm"](), invoice_id)
    return 200
