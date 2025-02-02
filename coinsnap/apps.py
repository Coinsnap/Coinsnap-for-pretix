from django.utils.translation import gettext_lazy
try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "coinsnap"
    verbose_name = "Bitcoin-Lightning Payment with Coinsnap"
    public_name = "Bitcoin-Lightning Payment with Coinsnap"

    class PretixPluginMeta:
        name = gettext_lazy("Bitcoin-Lightning Payment with Coinsnap")
        author = "Coinsnap Dev"
        public_name = "Bitcoin-Lightning Payment with Coinsnap"
        description = gettext_lazy("Accept Bitcoin-Lightning for your event with this easy-to-install, and easy-to mange, safe and secure plugin. Receive your payments in real-time, directly into your Lightning wallet, without any risk of fraud or charge-back. Coinsnap is the leading provider of software for Bitcoin-Lightning payment directly from your customer’s wallet into your wallet, and Coinsnap charges just 1,25% (or 1% with Referrer code) of the payment. By the way: Coinsnap never touches your Bitcon - we only facilitate the transfer from your customer to you.")
        visible = True
        version = '0.1.0'
        picture = "coinsnap/logo.png"
        category = "PAYMENT"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA
