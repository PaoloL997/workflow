from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Import qui dentro: prima di ``ready()`` i modelli non sono caricati.
        from core.services import scheduler

        scheduler.avvia_se_previsto()
