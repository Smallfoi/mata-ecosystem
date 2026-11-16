"""Реклама и служебные уведомления не смешиваются (LAUNCH_READINESS §6).

Канал у нас один — лента и пуши. Поэтому различие держится не на канале, а на
признаке `promotional` и проверке согласия перед отправкой. Тесты закрывают обе
ошибки, и вторая опаснее первой:
1. реклама ушла человеку без согласия;
2. служебное сообщение НЕ дошло, потому что человек отписался от рекламы.
"""
from django.test import TestCase
from django.utils import timezone

from legal.models import LegalDocument, UserConsent, has_marketing_consent
from notifications.models import Notification, create_notification, is_promotional


def _marketing_doc():
    return LegalDocument.objects.create(
        doc_type=LegalDocument.MARKETING, version="1.0", title="Рекламные коммуникации",
        is_required=False, published_at=timezone.now(),
    )


class PromotionalFlag(TestCase):
    def test_explicit_flag_wins_over_type(self):
        """Служебное сообщение о акции (напр. «ваш купон истекает») рекламой не станет."""
        self.assertTrue(is_promotional("system", promotional=True))
        self.assertFalse(is_promotional("promo", promotional=False))

    def test_promo_type_without_flag_counts_as_advertising(self):
        """Самая вероятная ошибка — отправить акцию и забыть флаг.

        Ошибаться надо в сторону «спросили согласие», а не «разослали без согласия».
        """
        self.assertTrue(is_promotional("promo"))
        self.assertFalse(is_promotional("order"))


class ServiceNotificationsAlwaysArrive(TestCase):
    """Отписка от рекламы не отключает человека от обязательных сообщений."""

    def test_order_status_arrives_without_any_consent(self):
        n = create_notification("u_1", "Заказ получен", type="order", order_id="SS-1")
        self.assertIsNotNone(n)
        self.assertFalse(n.promotional)

    def test_order_status_arrives_after_marketing_was_revoked(self):
        doc = _marketing_doc()
        UserConsent.objects.create(user_id="u_2", document=doc, revoked_at=timezone.now())
        self.assertFalse(has_marketing_consent("u_2"))

        n = create_notification("u_2", "Заказ отправлен", type="order")
        self.assertIsNotNone(n)
        self.assertEqual(Notification.objects.filter(user_id="u_2").count(), 1)


class AdvertisingNeedsConsent(TestCase):
    def test_no_consent_no_advertising_in_any_channel(self):
        """Без согласия не создаётся даже запись в ленте — и письмо не уходит.

        Проверка стоит ДО письма и пуша: иначе реклама ушла бы в другой канал, не
        оставив следа в ленте, и мы бы считали, что её не было.
        """
        sent = create_notification("u_3", "Скидка 20%", type="promo",
                                   email_to="u3@example.test")
        self.assertIsNone(sent)
        self.assertEqual(Notification.objects.filter(user_id="u_3").count(), 0)

    def test_revoked_consent_stops_advertising(self):
        doc = _marketing_doc()
        consent = UserConsent.objects.create(user_id="u_4", document=doc)
        self.assertIsNotNone(create_notification("u_4", "Акция", type="promo"))

        consent.revoked_at = timezone.now()
        consent.save()
        self.assertIsNone(create_notification("u_4", "Акция ещё раз", type="promo"))
        self.assertEqual(Notification.objects.filter(user_id="u_4").count(), 1)

    def test_active_consent_allows_advertising_and_marks_it(self):
        _marketing_doc_consent = _marketing_doc()
        UserConsent.objects.create(user_id="u_5", document=_marketing_doc_consent)

        n = create_notification("u_5", "Новая коллекция", type="promo")
        self.assertIsNotNone(n)
        self.assertTrue(n.promotional)
        self.assertTrue(n.to_json()["promotional"])

    def test_consent_to_another_document_is_not_consent_to_advertising(self):
        """Принятая политика конфиденциальности рекламу не разрешает."""
        privacy = LegalDocument.objects.create(
            doc_type=LegalDocument.PRIVACY, version="1.2", title="Политика",
            is_required=True, published_at=timezone.now(),
        )
        UserConsent.objects.create(user_id="u_6", document=privacy)

        self.assertFalse(has_marketing_consent("u_6"))
        self.assertIsNone(create_notification("u_6", "Распродажа", type="promo"))
