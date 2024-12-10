__version__ = "0.1.0"

from django.utils.translation import gettext_lazy as _
from pretix.base.plugins import PluginConfig

class CoinSnapPluginMeta(PluginConfig):
    name = 'coinsnap'
    verbose_name = 'Coinsnap Plugin'

    def ready(self):
        from . import signals  # NOQA

    def is_installed(self):
        return True