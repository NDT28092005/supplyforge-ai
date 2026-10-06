from django.apps import AppConfig


class SupplyforgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'supplyforge'

    def ready(self):
        try:
            import supplyforge.celery_telemetry  # Register Celery signal receivers
        except Exception:
            pass
