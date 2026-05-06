from django.apps import AppConfig


class InvigilatorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.invigilators"
    verbose_name = "Invigilators"

    def ready(self):
        # Import signals to register handlers, if added later.
        try:
            from . import signals  # noqa: F401
        except ImportError:
            pass
