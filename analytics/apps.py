from django.apps import AppConfig

class AnalyticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'analytics'
    
    def ready(self):
        # Import signals if you have any
        try:
            import analytics.signals
        except ImportError:
            pass
