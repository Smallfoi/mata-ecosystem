"""Точки подключения COROS: адреса из заявки должны отвечать без токена.

COROS проверяет их сам, до всякой авторизации — если они закрыты, интеграцию
не одобрят.
"""
from common.testutils import ApiTestCase


class CorosEndpointsTests(ApiTestCase):
    phone = "+79990009301"

    def test_status_is_public(self):
        r = self.client.get("/v1/integrations/coros/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_callback_is_public_and_survives_empty_call(self):
        r = self.client.get("/v1/integrations/coros/callback")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["received"])

    def test_callback_sees_code(self):
        r = self.client.get("/v1/integrations/coros/callback?code=abc&state=xyz")
        self.assertTrue(r.json()["received"])

    def test_push_accepts_list_of_workouts(self):
        r = self.client.post(
            "/v1/integrations/coros/push",
            data='[{"workoutId": "1"}, {"workoutId": "2"}]',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["received"], 2)

    def test_push_rejects_garbage(self):
        r = self.client.post(
            "/v1/integrations/coros/push", data="не json", content_type="application/json"
        )
        self.assertEqual(r.status_code, 400)

class SuuntoEndpointsTests(ApiTestCase):
    """Адреса Suunto: их вводят в кабинете партнёра, и они обязаны отвечать без токена.

    Suunto приняли нас в партнёрскую программу 05.10.2026. Адрес возврата проверяется
    при настройке приложения, адрес вебхука — при подписке на события; закрытый или
    отвечающий ошибкой адрес настроить не дадут.
    """

    phone = "+79990009302"

    def test_status_is_public(self):
        r = self.client.get("/v1/integrations/suunto/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_callback_is_public_and_survives_empty_call(self):
        """Человек передумал на странице Suunto — вернулся без кода, это не ошибка."""
        r = self.client.get("/v1/integrations/suunto/callback")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])

    def test_callback_without_valid_signature_is_refused(self):
        """Код без нашей подписи не подключает никого: иначе чужой аккаунт
        можно было бы привязать к любому пользователю (см. tests_suunto)."""
        r = self.client.get("/v1/integrations/suunto/callback?code=abc&state=xyz")
        self.assertEqual(r.status_code, 400)

    def test_push_accepts_event(self):
        r = self.client.post(
            "/v1/integrations/suunto/push",
            data='{"workoutid": "1", "username": "u"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["received"], 1)

    def test_push_rejects_garbage(self):
        r = self.client.post(
            "/v1/integrations/suunto/push", data="не json", content_type="application/json"
        )
        self.assertEqual(r.status_code, 400)

