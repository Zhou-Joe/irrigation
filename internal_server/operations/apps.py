from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'operations'
    verbose_name = '多团队现场作业'

    def ready(self):
        from . import signals  # noqa: F401
