from django.db import models


class RefCoinsnapObject(models.Model):
    reference = models.CharField(max_length=190, db_index=True, unique=True)
    order = models.ForeignKey("pretixbase.Order", on_delete=models.CASCADE)
    payment = models.ForeignKey(
        "pretixbase.OrderPayment", null=True, blank=True, on_delete=models.CASCADE
    )
from django.db import models

class CoinsnapWebhookState(models.Model):
    key = models.CharField(max_length=255, unique=True)
    is_connected_to_webhook = models.BooleanField(default=False)
    secret = models.CharField(max_length=255, blank=True, null=True)
    webhook_id = models.CharField(max_length=255, blank=True, null=True)

    @classmethod
    def get(cls):
        """Fetch the connection state."""
        try:
            return cls.objects.get(key='webhook_connection').is_connected_to_webhook
        except cls.DoesNotExist:
            return False

    @classmethod
    def set(cls, value):
        """Update the connection state."""
        state, created = cls.objects.get_or_create(key='webhook_connection')
        state.is_connected_to_webhook = value
        state.save()

    @classmethod
    def get_secret(cls):
        """Fetch the secret."""
        try:
            return cls.objects.get(key='webhook_connection').secret
        except cls.DoesNotExist:
            return None

    @classmethod
    def set_secret(cls, value):
        """Update the secret."""
        state, created = cls.objects.get_or_create(key='webhook_connection')
        state.secret = value
        state.save()

    @classmethod
    def get_webhook_id(cls):
        """Fetch the webhook_id."""
        try:
            return cls.objects.get(key='webhook_connection').webhook_id
        except cls.DoesNotExist:
            return None

    @classmethod
    def set_webhook_id(cls, value):
        """Update the webhook_id."""
        state, created = cls.objects.get_or_create(key='webhook_connection')
        state.webhook_id = value
        state.save()
