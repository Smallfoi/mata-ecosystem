from django.apps import AppConfig


class LoyaltyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "loyalty"
    verbose_name = "Баллы"

    def ready(self):
        from . import signals  # noqa: F401  — зеркало старого реестра в лоты v1
