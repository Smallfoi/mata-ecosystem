from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analytics"
    verbose_name = "Аналитика"

    def ready(self):
        # Статистика продаж пишется при оплате заказа — сигналом, чтобы не зависеть от
        # того, каким путём заказ стал оплаченным (вебхук, сверка, тестовая оплата).
        from django.db.models.signals import post_save

        from orders.models import Order

        from .sales import on_order_saved

        post_save.connect(on_order_saved, sender=Order, dispatch_uid="analytics_sale_lines")
