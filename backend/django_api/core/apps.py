from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        # Регистрирует системные проверки окружения (сторож свежести образа).
        from common import checks  # noqa: F401
