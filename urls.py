from django.urls import path
from . import views

urlpatterns = [
        path(
        'pretix/webhooks/coinsnap',
        views.coinsnap_webhook,
        name='coinsnap_webhook'
    ),
]
