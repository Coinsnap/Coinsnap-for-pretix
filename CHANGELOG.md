# Changelog

## 0.2.0

- Security: The webhook no longer confirms payments from what the request says. It verifies the timestamped `X-Coinsnap-Signature` header with a timing-safe comparison, then asks the Coinsnap API about the invoice. A payment is confirmed only when the invoice is settled, belongs to that order, and matches the payment's amount and currency; and only once.
- Security: The webhook secret is kept per Coinsnap store. Before, one secret was shared by every event and organizer on the pretix instance, so webhooks from one organizer's store could confirm another organizer's orders.
- Security: Each payment records the invoice created for it; another invoice cannot confirm it.
- Security: The API key is shown redacted in the settings; saving the form unchanged keeps it.
- Security: The webhook URL is built from the configured site URL, not from the request's Host header.
- Fix: Invoice amounts are sent as exact decimals, API calls have timeouts, and a failed invoice creation shows an error instead of a server error.
- Fix: A payment server outage no longer replaces the webhook.
