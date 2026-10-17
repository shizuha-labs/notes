from django.apps import AppConfig


class NotesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notes'
    verbose_name = 'Shizuha Notes'

    def ready(self):
        import notes.signals  # noqa
