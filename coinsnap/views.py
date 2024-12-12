from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_scopes import scope
from coinsnap.models import CoinsnapWebhookState, RefCoinsnapObject
import hmac
import json
import hashlib

@csrf_exempt
def coinsnap_webhook(request):
    """
    Handles Coinsnap webhook notifications.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)
    CoinsnapWebhookState.objects.get_or_create(key='webhook_connection', defaults={'is_connected_to_webhook': False})
    webhook_state = CoinsnapWebhookState.get()

    secret = CoinsnapWebhookState.get_secret()
    signature = request.headers.get("X-Coinsnap-Sig")
    if signature:
        signature = signature.replace("sha256=", "")
    computed_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=request.body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    payload = json.loads(request.body)

    if(webhook_state):
        if not hmac.compare_digest(str(signature), str(computed_signature)):
            return JsonResponse({"error": "Invalid signature"}, status=400)

        order_id = payload.get('metadata').get("orderId")
        payment_status = payload.get("type")
        if order_id and payment_status == 'Settled':
            rso = RefCoinsnapObject.objects.select_related(
                "order", "order__event"
            ).get(reference=order_id)
            organizer = rso.order.event.organizer
            with scope(organizer=organizer):
                rso.payment.confirm()
            return JsonResponse({"status": "ok"})
        else: # status New and Processing
            return JsonResponse({"status": "ok"})
        
    if(payload and payload.get('purpose', False) == "webhook_url_validation"): #Initial creation doesn't have signature
        return JsonResponse({"status": "ok"})
    else:
        return JsonResponse({"error": "Invalid status"}, status=400)
 
