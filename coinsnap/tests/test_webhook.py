"""Webhook and payment decision tests, with the Coinsnap API mocked.

Run inside a pretix test environment (pytest + pytest-django, DJANGO_SETTINGS_MODULE=pretix.testutils.settings),
with this package importable as `coinsnap` and registered as a `pretix.plugin` entry point, from the repo root:
    python -m pytest -c coinsnap/setup.cfg --rootdir=coinsnap coinsnap/tests
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import timedelta
from decimal import Decimal

import pytest
import requests
from django.conf import settings as django_settings
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils.timezone import now
from django_scopes import scope, scopes_disabled
from pretix.base.models import Event, Order, OrderPayment, Organizer, Quota
from pretix.base.settings import GlobalSettingsObject

from coinsnap import store_webhooks, views, webhook
from coinsnap.payment import CoinsnapPayment

API_KEY = "apikey-0123456789-SECRETKEY"
STORE_A = "STOREAAAAAAAAAAAA"
STORE_B = "STOREBBBBBBBBBBBB"
SECRET_A = "secretAAAAAAAAAAAAAAAAAAAAAAAAAA"
SECRET_B = "secretBBBBBBBBBBBBBBBBBBBBBBBBBB"
LEGACY_SECRET = "legacysecretLLLLLLLLLLLLLLLLLLLL"


def sign(body, secret, t=None):
    t = int(time.time()) if t is None else t
    v1 = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


class FakeApi:
    """Stands in for app.coinsnap.io: invoices by (store, id), counts calls."""

    def __init__(self):
        self.invoices = {}
        self.status = None
        self.raise_error = False
        self.calls = []
        self.posted = []

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.calls.append(url)
        assert kwargs.get("verify", True) is True
        if self.raise_error:
            raise requests.exceptions.ConnectionError("down")
        parts = url.split("/")
        store, invoice_id = parts[-3], parts[-1]
        response = requests.Response()
        if self.status:
            response.status_code = self.status
            response._content = b"{}"
            return response
        invoice = self.invoices.get((store, invoice_id))
        response.status_code = 200 if invoice else 400
        response._content = json.dumps(invoice or {"error": "not found"}).encode()
        return response

    def post(self, url, json=None, headers=None, timeout=None, **kwargs):
        import json as _json

        self.posted.append((url, json))
        response = requests.Response()
        response.status_code = 200
        n = len(self.posted)
        response._content = _json.dumps({"id": f"inv{n}", "checkoutLink": f"https://pay.example/inv{n}"}).encode()
        return response


@pytest.fixture(autouse=True)
def fresh_log_limit():
    views._local_count[:] = [0, 0]


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(views.requests, "get", fake.get)
    monkeypatch.setattr("coinsnap.payment.requests.post", fake.post)
    return fake


def make_event(slug, store_id, secret):
    organizer = Organizer.objects.create(name=slug, slug=slug)
    with scope(organizer=organizer):
        event = Event.objects.create(
            organizer=organizer, name=slug, slug=slug, date_from=now() + timedelta(days=5),
            plugins="coinsnap", currency="EUR",
        )
        event.settings.set("payment_coinsnap__enabled", True)
        event.settings.set("payment_coinsnap_store_id", store_id)
        event.settings.set("payment_coinsnap_api_key", API_KEY)
    if secret is not None:
        store_webhooks.save(store_id, secret, f"wh-{store_id}")
    return event


def sales_channel(organizer):
    # pretix >= 2024.x requires a sales channel object; older versions take none.
    channels = getattr(organizer, "sales_channels", None)
    return {"sales_channel": channels.get(identifier="web")} if channels is not None else {}


def make_payment(event, code, info, total="13.37", state=OrderPayment.PAYMENT_STATE_CREATED):
    with scope(organizer=event.organizer):
        order = Order.objects.create(
            code=code, event=event, email="buyer@example.org", status=Order.STATUS_PENDING,
            datetime=now(), expires=now() + timedelta(days=10), total=Decimal(total),
            **sales_channel(event.organizer),
        )
        return order.payments.create(provider="coinsnap", amount=order.total, state=state, info=json.dumps(info))


def new_info(invoice_id, amount="13.37", currency="EUR", code="ABCDE"):
    return {"invoiceId": invoice_id, "invoices": [{"id": invoice_id, "amount": amount, "currency": currency}],
            "amount": amount, "currency": currency, "orderID": f"DUMMY-{code}"}


def settled(event, code, amount=13.37, currency="EUR", status="Settled"):
    return {"status": status, "orderId": f"{event.slug.upper()}-{code}", "invoiceAmount": amount,
            "currency": currency, "amount": 123456}


def post(body, header):
    client = Client(HTTP_HOST="example.com")
    url = reverse("plugins:coinsnap:coinsnap_webhook")
    kwargs = {"HTTP_X_COINSNAP_SIGNATURE": header} if header is not None else {}
    return client.post(url, data=body, content_type="application/json", **kwargs)


def body_for(invoice_id, type_="Settled", order_code=None):
    data = {"type": type_, "invoiceId": invoice_id}
    if order_code:
        data["metadata"] = {"orderId": order_code}
    return json.dumps(data).encode()


def state(payment):
    with scopes_disabled():
        payment.refresh_from_db()
        payment.order.refresh_from_db()
        return payment.state, payment.order.status


@pytest.fixture
def shop(db):
    event = make_event("dummy", STORE_A, SECRET_A)
    payment = make_payment(event, "ABCDE", new_info("invA1"))
    return event, payment


# --- Signature, checked before anything else -------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("header", [None, "", "t=1,v1=00", "garbage"])
def test_missing_or_bad_signature_is_401_and_calls_nothing(shop, api, caplog, header):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    caplog.set_level(logging.INFO, logger="coinsnap")
    r = post(body_for("invA1"), header)
    assert r.status_code == 401
    assert api.calls == []
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED
    assert "SECURITY webhook reason=bad signature" in caplog.text


@pytest.mark.django_db
def test_wrong_secret_is_401(shop, api):
    r = post(body_for("invA1"), sign(body_for("invA1"), "not-the-secret"))
    assert r.status_code == 401


@pytest.mark.django_db
def test_stale_timestamp_is_401(shop, api, caplog):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    body = body_for("invA1")
    r = post(body, sign(body, SECRET_A, int(time.time()) - 600))
    assert r.status_code == 401
    assert "reason=stale timestamp" in caplog.text
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_empty_secret_rejects_everything(db, api):
    event = make_event("dummy", STORE_A, "")
    payment = make_payment(event, "ABCDE", new_info("invA1"))
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    body = body_for("invA1")
    assert post(body, sign(body, "")).status_code == 401
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_get_is_not_allowed(shop):
    assert Client(HTTP_HOST="example.com").get(reverse("plugins:coinsnap:coinsnap_webhook")).status_code == 405


# --- Decide from the API ----------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_real_payment_confirms_once(shop, api, caplog):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    caplog.set_level(logging.INFO, logger="coinsnap")
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment) == (OrderPayment.PAYMENT_STATE_CONFIRMED, Order.STATUS_PAID)
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert "reason=already processed" in caplog.text
    with scopes_disabled():
        assert payment.order.all_logentries().filter(action_type="pretix.event.order.payment.confirmed").count() == 1


@pytest.mark.django_db
def test_dashboard_test_webhook_changes_nothing(shop, api, caplog):
    caplog.set_level(logging.INFO, logger="coinsnap")
    event, payment = shop
    body = body_for("test_123", order_code="DUMMY-ABCDE")
    r = post(body, sign(body, SECRET_A))
    assert r.status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED
    assert "INFO webhook reason=not ours invoice=test_123" in caplog.text
    assert "SECURITY" not in caplog.text


@pytest.mark.django_db
def test_unknown_invoice_at_api_is_200(shop, api, caplog):
    caplog.set_level(logging.INFO, logger="coinsnap")
    event, payment = shop  # invA1 recorded, but the API does not know it
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert "reason=unknown invoice" in caplog.text
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["500", "connection"])
def test_api_down_is_503(shop, api, mode):
    event, payment = shop
    if mode == "500":
        api.status = 500
    else:
        api.raise_error = True
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 503
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_forged_settled_is_logged_and_ignored(shop, api, caplog):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE", status="New")
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert "SECURITY webhook reason=forged status invoice=invA1" in caplog.text
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
@pytest.mark.parametrize("invoice_changes", [
    {"invoiceAmount": 1.00},                       # underpaid
    {"invoiceAmount": 0},                          # zero
    {"invoiceAmount": None, "fiatAmount": None},   # no amount
    {"currency": "USD"},                           # other currency
    {"orderId": "DUMMY-OTHER"},                    # another order's invoice
])
def test_what_was_paid_must_match(shop, api, invoice_changes):
    event, payment = shop
    invoice = settled(event, "ABCDE")
    invoice.update(invoice_changes)
    api.invoices[(STORE_A, "invA1")] = invoice
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_fiat_amount_fallback(shop, api):
    event, payment = shop
    invoice = settled(event, "ABCDE")
    invoice.update({"invoiceAmount": None, "fiatAmount": "13.37"})
    api.invoices[(STORE_A, "invA1")] = invoice
    body = body_for("invA1")
    post(body, sign(body, SECRET_A))
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED


@pytest.mark.django_db
def test_invoice_not_recorded_for_payment_is_not_ours(shop, api):
    event, payment = shop
    # A real settled invoice of the same store and order, but not one this plugin created for the payment.
    api.invoices[(STORE_A, "invX")] = settled(event, "ABCDE")
    body = body_for("invX", order_code="DUMMY-ABCDE")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


# --- Never backwards; manual state wins (6.8) ---------------------------------------------------------------------

@pytest.mark.django_db
def test_refunded_payment_is_not_confirmed_again(shop, api, caplog):
    caplog.set_level(logging.INFO, logger="coinsnap")
    event, payment = shop
    with scopes_disabled():
        OrderPayment.objects.filter(pk=payment.pk).update(state=OrderPayment.PAYMENT_STATE_REFUNDED)
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_REFUNDED
    assert "no change: payment refunded" in caplog.text


@pytest.mark.django_db
def test_expired_after_paid_changes_nothing(shop, api):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    body = body_for("invA1")
    post(body, sign(body, SECRET_A))
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE", status="Expired")
    body = body_for("invA1", type_="Expired")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment) == (OrderPayment.PAYMENT_STATE_CONFIRMED, Order.STATUS_PAID)


@pytest.mark.django_db
def test_quota_exceeded_still_records_the_payment(shop, api, monkeypatch, caplog):
    event, payment = shop
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    original = OrderPayment.confirm

    def confirm_then_quota(self, *a, **kw):
        OrderPayment.objects.filter(pk=self.pk).update(state=OrderPayment.PAYMENT_STATE_CONFIRMED)
        raise Quota.QuotaExceededException("full")

    monkeypatch.setattr(OrderPayment, "confirm", confirm_then_quota)
    body = body_for("invA1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    monkeypatch.setattr(OrderPayment, "confirm", original)
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED
    assert "quota is exhausted" in caplog.text


# --- Per-store secrets (6.4) ------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_two_stores_each_accept_only_their_own(db, api):
    event_a = make_event("alpha", STORE_A, SECRET_A)
    event_b = make_event("beta", STORE_B, SECRET_B)
    pay_a = make_payment(event_a, "AAAAA", new_info("invA"))
    pay_b = make_payment(event_b, "BBBBB", new_info("invB"))
    api.invoices[(STORE_A, "invA")] = settled(event_a, "AAAAA")
    api.invoices[(STORE_B, "invB")] = settled(event_b, "BBBBB")

    # Store B's secret cannot confirm store A's payment.
    body = body_for("invA")
    assert post(body, sign(body, SECRET_B)).status_code == 200
    assert state(pay_a)[0] == OrderPayment.PAYMENT_STATE_CREATED

    assert post(body, sign(body, SECRET_A)).status_code == 200
    body = body_for("invB")
    assert post(body, sign(body, SECRET_B)).status_code == 200
    assert state(pay_a)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED
    assert state(pay_b)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED


# --- Every invoice kept (6.7), legacy window --------------------------------------------------------------------

@pytest.mark.django_db
def test_two_invoices_for_one_payment_first_one_pays(shop, api):
    event, payment = shop
    with scopes_disabled():
        OrderPayment.objects.filter(pk=payment.pk).update(info="{}")
        payment.refresh_from_db()
    provider = CoinsnapPayment(event)
    request = RequestFactory().get("/", HTTP_HOST="evil.example")
    with scope(organizer=event.organizer):
        provider.execute_payment(request, payment)
        provider.execute_payment(request, payment)
    with scopes_disabled():
        payment.refresh_from_db()
        info = json.loads(payment.info)
    assert [r["id"] for r in info["invoices"]] == ["inv1", "inv2"]
    # Price, currency and redirect come from the server.
    url, sent = api.posted[0]
    assert sent["amount"] == "13.37" and sent["currency"] == "EUR" and sent["orderId"] == "DUMMY-ABCDE"
    assert "evil.example" not in sent["redirectUrl"]
    assert sent["redirectUrl"].startswith(django_settings.SITE_URL)

    api.invoices[(STORE_A, "inv1")] = settled(event, "ABCDE")
    body = body_for("inv1")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED


def legacy_setup(db_event_secret=SECRET_A, upgraded_hours_ago=1):
    event = make_event("dummy", STORE_A, db_event_secret)
    payment = make_payment(event, "ABCDE", {"amount": "13.37", "currency": "EUR", "orderID": "DUMMY-ABCDE"})
    GlobalSettingsObject().settings.set(store_webhooks.UPGRADED_AT, str(int(time.time()) - upgraded_hours_ago * 3600))
    return event, payment


@pytest.mark.django_db
def test_legacy_payment_with_legacy_secret_inside_window(db, api, monkeypatch):
    event, payment = legacy_setup()
    monkeypatch.setattr(store_webhooks, "legacy_secret", lambda: LEGACY_SECRET)
    api.invoices[(STORE_A, "oldinv")] = settled(event, "ABCDE")
    body = body_for("oldinv", order_code="DUMMY-ABCDE")
    assert post(body, sign(body, LEGACY_SECRET)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED


@pytest.mark.django_db
def test_legacy_payment_with_store_secret_inside_window(db, api):
    event, payment = legacy_setup()
    api.invoices[(STORE_A, "oldinv")] = settled(event, "ABCDE")
    body = body_for("oldinv", order_code="DUMMY-ABCDE")
    assert post(body, sign(body, SECRET_A)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CONFIRMED


@pytest.mark.django_db
def test_legacy_payment_after_window_is_refused(db, api, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="coinsnap")
    event, payment = legacy_setup(upgraded_hours_ago=25)
    monkeypatch.setattr(store_webhooks, "legacy_secret", lambda: LEGACY_SECRET)
    api.invoices[(STORE_A, "oldinv")] = settled(event, "ABCDE")
    body = body_for("oldinv", order_code="DUMMY-ABCDE")
    assert post(body, sign(body, LEGACY_SECRET)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED
    assert "reason=not ours" in caplog.text
    assert api.calls == []


@pytest.mark.django_db
def test_legacy_secret_cannot_confirm_new_payments(shop, api, monkeypatch):
    event, payment = shop
    monkeypatch.setattr(store_webhooks, "legacy_secret", lambda: LEGACY_SECRET)
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE")
    body = body_for("invA1", order_code="DUMMY-ABCDE")
    assert post(body, sign(body, LEGACY_SECRET)).status_code == 200
    assert state(payment)[0] == OrderPayment.PAYMENT_STATE_CREATED


@pytest.mark.django_db
def test_legacy_secret_from_old_table(db):
    from django.db import connection

    with connection.cursor() as c:
        c.execute("CREATE TABLE coinsnap_coinsnapwebhookstate (id integer primary key, \"key\" varchar(255), "
                  "is_connected_to_webhook bool, secret varchar(255), webhook_id varchar(255))")
        c.execute("INSERT INTO coinsnap_coinsnapwebhookstate VALUES (1, 'webhook_connection', 1, %s, 'x')",
                  [LEGACY_SECRET])
    assert store_webhooks.legacy_secret() == LEGACY_SECRET


# --- Secrets stay on the server; logs ----------------------------------------------------------------------------

@pytest.mark.django_db
def test_templates_and_logs_carry_no_secrets_or_store_id(shop, api, caplog):
    caplog.set_level(logging.DEBUG)
    event, payment = shop
    provider = CoinsnapPayment(event)
    request = RequestFactory().get("/")
    html = provider.payment_form_render(request) + provider.checkout_confirm_render(request)
    for value in (API_KEY, STORE_A, SECRET_A):
        assert value not in html
    with scope(organizer=event.organizer):
        assert provider.settings_form_fields["api_key"].__class__.__name__ == "SecretKeySettingsField"

    # Exercise every rejection and the API error path, then check the log.
    api.invoices[(STORE_A, "invA1")] = settled(event, "ABCDE", status="New")
    body = body_for("invA1")
    post(body, "t=1,v1=00")
    post(body, sign(body, SECRET_A, int(time.time()) - 600))
    post(body, sign(body, SECRET_A))
    api.status = 500
    post(body, sign(body, SECRET_A))
    for value in (API_KEY, STORE_A, SECRET_A, "v1=", "buyer@example.org"):
        assert value not in caplog.text
    assert caplog.text.count("SECURITY webhook reason=") == 3


@pytest.mark.django_db
def test_webhook_url_from_site_url(shop):
    event, payment = shop
    assert CoinsnapPayment(event).webhook_url() == django_settings.SITE_URL + "/pretix/webhooks/coinsnap"


@pytest.mark.django_db
def test_security_log_is_rate_limited(shop, api, caplog):
    for _ in range(15):
        post(body_for("invA1"), "t=1,v1=00")
    assert caplog.text.count("SECURITY webhook reason=bad signature") == 10
    assert "more rejections this minute" in caplog.text


# --- Pure rules -------------------------------------------------------------------------------------------------

def test_decide():
    inv = {"status": "Settled", "invoiceAmount": 13.37, "currency": "EUR"}
    assert webhook.decide(inv, "13.37", "EUR") == webhook.PAID
    assert webhook.decide(dict(inv, invoiceAmount=13.36), "13.37", "EUR") == webhook.PAID  # 1 cent rounding
    assert webhook.decide(dict(inv, invoiceAmount=13.35), "13.37", "EUR") == webhook.MISMATCH
    assert webhook.decide(dict(inv, status="Processing"), "13.37", "EUR") == webhook.PROCESSING
    assert webhook.decide(dict(inv, status="Invalid"), "13.37", "EUR") == webhook.NONE
    assert webhook.decide(dict(inv, invoiceAmount=0), "0", "EUR") == webhook.MISMATCH
    assert webhook.decide(dict(inv, invoiceAmount="abc"), "13.37", "EUR") == webhook.MISMATCH


def test_signature_rules():
    body = b'{"invoiceId":"x"}'
    t = int(time.time())
    assert webhook.signature_problem(sign(body, "s", t), body, "s", t) is None
    assert webhook.signature_problem(sign(body, "s", t), body + b" ", "s", t) == "bad signature"
    assert webhook.signature_problem(sign(body, "", t), body, "", t) == "bad signature"
    assert webhook.signature_problem(sign(body, "s", t - 301), body, "s", t) == "stale timestamp"
    assert webhook.signature_problem("sha256=abc", body, "s", t) == "bad signature"
