from django.apps import AppConfig


class SupplyforgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'supplyforge'

    def ready(self):
        try:
            import supplyforge.celery_telemetry  # Register Celery signal receivers
        except Exception:
            pass
        try:
            from supplyforge.business_metrics_collector import register_business_snapshot_collector

            register_business_snapshot_collector()
        except Exception:
            # Metrics must never prevent the application from serving traffic.
            pass
