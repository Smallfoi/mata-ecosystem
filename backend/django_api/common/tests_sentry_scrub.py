"""Вычистка ПДн из событий об ошибках (D-32).

Проверяем не «вызывается ли функция», а то, ради чего она есть: телефон, почта
и токен НЕ должны уехать в трекер ошибок. Плюс отдельно — что вычистка не может
отменить отправку события: сломанный фильтр означал бы, что мы перестаём видеть
ошибки вообще.
"""
from django.test import SimpleTestCase

from common.sentry_scrub import REDACTED, before_breadcrumb, before_send, scrub, scrub_text


class LeakTests(SimpleTestCase):
    """Что не должно уехать наружу."""

    def test_russian_phone_in_message(self):
        text = scrub_text("пользователь +79148278470 не найден")
        self.assertNotIn("79148278470", text)
        self.assertIn(REDACTED, text)

    def test_phone_with_separators(self):
        for raw in ["+7 914 827-84-70", "8(914)827-84-70", "8 914 827 84 70"]:
            with self.subTest(phone=raw):
                self.assertNotIn("8470", scrub_text(f"звонок {raw} провален"))

    def test_email(self):
        text = scrub_text("KeyError: 'burv@infostart14.ru'")
        self.assertNotIn("infostart14", text)
        self.assertIn("KeyError", text)   # сама ошибка осталась читаемой

    def test_jwt(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1XzEifQ.c2lnbmF0dXJl"
        self.assertNotIn("eyJ", scrub_text(f"токен {token} просрочен"))

    def test_long_hex_looks_like_a_key(self):
        self.assertNotIn("a" * 40, scrub_text("ключ " + "a" * 40))

    def test_card_number(self):
        self.assertNotIn("4276", scrub_text("оплата картой 4276 3800 1234 5678"))


class StructureTests(SimpleTestCase):
    """Событие — вложенная структура, а не строка."""

    def test_secret_keys_are_cut_by_name(self):
        out = scrub({"password": "hunter2", "authorization": "Bearer abc",
                     "csrf_token": "xyz", "name": "Михаил"})
        self.assertEqual(out["password"], REDACTED)
        self.assertEqual(out["authorization"], REDACTED)
        self.assertEqual(out["csrf_token"], REDACTED)
        self.assertEqual(out["name"], "Михаил")   # обычное поле не трогаем

    def test_nested_values_are_cleaned(self):
        event = {"exception": {"values": [
            {"value": "нет пользователя +79148278470",
             "stacktrace": {"frames": [{"vars": {"email": "a@b.ru"}}]}}
        ]}}
        out = scrub(event)
        dumped = str(out)
        self.assertNotIn("79148278470", dumped)
        self.assertNotIn("a@b.ru", dumped)

    def test_lists_and_tuples_survive_their_type(self):
        out = scrub({"a": ["+79148270000"], "b": ("x@y.ru",)})
        self.assertIsInstance(out["a"], list)
        self.assertIsInstance(out["b"], tuple)
        self.assertNotIn("79148270000", str(out))

    def test_deep_structure_does_not_hang(self):
        """Глубина ограничена: событие может быть аномально вложенным."""
        deep = current = {}
        for _ in range(50):
            current["next"] = {}
            current = current["next"]
        current["value"] = "+79148270000"
        scrub(deep)   # не должно ни зациклиться, ни упасть

    def test_very_long_string_is_trimmed(self):
        out = scrub_text("x" * 20000)
        self.assertLess(len(out), 20000)


class NeverBreaksSendingTests(SimpleTestCase):
    """Сломанный фильтр = мы слепые. Этого допустить нельзя."""

    def test_event_is_returned_even_if_scrub_fails(self):
        class Exploding(dict):
            def items(self):
                raise RuntimeError("внутренний сбой")

        event = Exploding(a=1)
        self.assertIs(before_send(event, None), event)

    def test_breadcrumb_is_returned_even_if_scrub_fails(self):
        class Exploding(dict):
            def items(self):
                raise RuntimeError("внутренний сбой")

        crumb = Exploding(a=1)
        self.assertIs(before_breadcrumb(crumb, None), crumb)

    def test_normal_event_passes_through_cleaned(self):
        event = {"message": "сбой у +79148270000"}
        out = before_send(event, None)
        self.assertNotIn("79148270000", str(out))


class KeepsUsefulnessTests(SimpleTestCase):
    """Вычистка не должна превращать ошибку в бесполезную."""

    def test_error_type_and_place_survive(self):
        text = scrub_text(
            "ValueError в orders/pricing.py:42 — сумма для +79148270000 отрицательная")
        for keep in ["ValueError", "orders/pricing.py:42", "отрицательная"]:
            self.assertIn(keep, text)

    def test_plain_numbers_are_not_eaten(self):
        """Короткие числа (сумма, размер, код ответа) — не персональные данные."""
        text = scrub_text("заказ на 6 пар, размер 41, ответ 500")
        self.assertIn("6", text)
        self.assertIn("41", text)
        self.assertIn("500", text)


class DashboardTileTests(SimpleTestCase):
    """Плитка «Ошибки» на главной не должна ронять главную (D-32).

    Трекер — внешняя система: не настроен, лёг, отвечает мусором. Дашборд с
    выручкой и заказами обязан открыться в любом из этих случаев.
    """

    def test_tile_is_dash_when_tracker_not_configured(self):
        """Состояние трекера задаём явно: в dev он бывает поднят локально,
        и тест, зависящий от окружения, врал бы через раз."""
        from unittest import mock

        from config.dashboard import _errors_tile

        with mock.patch("common.glitchtip.is_configured", return_value=False):
            tile = _errors_tile()
        self.assertEqual(tile["title"], "Ошибки")
        self.assertEqual(tile["value"], "—")

    def test_tile_survives_tracker_exploding(self):
        from unittest import mock

        from config.dashboard import _errors_tile

        with mock.patch("common.glitchtip.is_configured", return_value=True), \
             mock.patch("common.glitchtip.fetch_issues",
                        side_effect=RuntimeError("трекер лёг")):
            tile = _errors_tile()
        self.assertEqual(tile["value"], "—")

    def test_tile_reports_no_connection(self):
        from unittest import mock

        from config.dashboard import _errors_tile

        with mock.patch("common.glitchtip.is_configured", return_value=True), \
             mock.patch("common.glitchtip.fetch_issues",
                        return_value=([], "таймаут")):
            tile = _errors_tile()
        self.assertEqual(tile["value"], "нет связи")

    def test_tile_counts_unresolved_errors(self):
        from unittest import mock

        from config.dashboard import _errors_tile

        issues = [{"level": "error", "status": "unresolved", "count": 3},
                  {"level": "fatal", "status": "unresolved", "count": 1},
                  {"level": "info", "status": "unresolved", "count": 9}]
        with mock.patch("common.glitchtip.is_configured", return_value=True), \
             mock.patch("common.glitchtip.fetch_issues", return_value=(issues, None)):
            tile = _errors_tile()
        self.assertEqual(tile["value"], 2)   # info не ошибка
