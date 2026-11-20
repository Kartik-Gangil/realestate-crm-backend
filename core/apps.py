from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        from .audit_signals import register_audit_signals

        register_audit_signals()
