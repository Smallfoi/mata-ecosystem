# -*- coding: utf-8 -*-
"""Подключение и опрос COROS.

Главное отличие от Suunto, которое и проверяем: COROS не выдаёт ключи руками —
наш сервер регистрирует приложение сам, а о новых тренировках узнаёт опросом, а
не из уведомления. Плюс обязательная защита кода (PKCE): без секрета-проверки,
который остаётся у нас, перехваченный код бесполезен.
"""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone

from common.testutils import ApiTestCase
from integrations import coros
from integrations.models import McpClient, WatchAccount
from integrations.tasks import poll_coros, poll_coros_all
from workouts.models import ExternalWorkout
from workouts.tests_trust import _drawn_track, _recorded_track

META = {
    "issuer": "https://mcpeu.coros.com",
    "authorization_endpoint": "https://mcpeu.coros.com/oauth2/authorize",
    "token_endpoint": "https://mcpeu.coros.com/oauth2/token",
    "registration_endpoint": "https://mcpeu.coros.com/connect/register",
}
REGISTERED = {"client_id": "cid-1", "client_secret": "csec-1"}
TOKENS = {"access_token": "acc-1", "refresh_token": "ref-1",
          "expires_in": 3600, "sub": "coros-user-1"}


def _record(source_id="a-1", hours_ago=2, distance=6000, duration=2100):
    return {
        "labelId": source_id,
        "sportType": "run",
        "startTime": int((timezone.now() - timedelta(hours=hours_ago)).timestamp() * 1000),
        "distance": distance,
        "totalTime": duration,
    }


@mock.patch("integrations.coros.metadata", return_value=META)
class CorosConnectTests(ApiTestCase):
    phone = "+79990009401"

    def setUp(self):
        super().setUp()
        cache.clear()

    @mock.patch("integrations.coros.register_client", return_value=REGISTERED)
    def test_connect_registers_app_itself_and_returns_link(self, m_register, m_meta):
        """Ключей никто не выдаёт — сервер заводит приложение сам."""
        r = self.api_get("/v1/integrations/coros/connect")
        self.assertEqual(r.status_code, 200)
        url = r.json()["url"]
        self.assertIn("mcpeu.coros.com/oauth2/authorize", url)
        self.assertIn("client_id=cid-1", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertEqual(McpClient.objects.filter(source="coros").count(), 1)

    @mock.patch("integrations.coros.register_client", return_value=REGISTERED)
    def test_second_connect_reuses_the_same_app(self, m_register, m_meta):
        """Повторная регистрация означала бы новое приложение и отвал всех людей."""
        self.api_get("/v1/integrations/coros/connect")
        self.api_get("/v1/integrations/coros/connect")
        self.assertEqual(m_register.call_count, 1)

    def test_connect_requires_login(self, m_meta):
        self.assertEqual(self.client.get("/v1/integrations/coros/connect").status_code, 401)

    @mock.patch("integrations.coros.register_client", return_value=REGISTERED)
    @mock.patch("integrations.coros.exchange_code", return_value=TOKENS)
    def test_callback_saves_account(self, m_exchange, m_register, m_meta):
        state = self._state_from_link()
        r = self.client.get(f"/v1/integrations/coros/callback?code=abc&state={state}")
        self.assertTrue(r.json()["ok"])
        acc = WatchAccount.objects.get(user_id=self.uid, source="coros")
        self.assertEqual(acc.access_token, "acc-1")
        # Секрет-проверка одноразовая: второй заход по той же ссылке не пройдёт.
        again = self.client.get(f"/v1/integrations/coros/callback?code=abc&state={state}")
        self.assertEqual(again.status_code, 400)

    def _state_from_link(self):
        import urllib.parse
        with mock.patch("integrations.coros.register_client", return_value=REGISTERED):
            url = self.api_get("/v1/integrations/coros/connect").json()["url"]
        return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    @mock.patch("integrations.coros.register_client", return_value=REGISTERED)
    def test_callback_rejects_forged_state(self, m_register, m_meta):
        r = self.client.get("/v1/integrations/coros/callback?code=abc&state=подделка")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(WatchAccount.objects.count(), 0)

    @mock.patch("integrations.coros.register_client",
                side_effect=coros.CorosError("сервер молчит"))
    def test_connect_when_coros_is_down_says_so(self, m_register, m_meta):
        self.assertEqual(self.api_get("/v1/integrations/coros/connect").status_code, 503)


class CorosPollTests(ApiTestCase):
    phone = "+79990009402"

    def setUp(self):
        super().setUp()
        McpClient.objects.update_or_create(
            source="coros",
            defaults={"client_id": "cid-1", "client_secret": "csec-1",
                      "redirect_uri": "https://api.mata-club.ru/v1/integrations/coros/callback"},
        )
        self.account = WatchAccount.objects.create(
            user_id=self.uid, source="coros", external_id="coros-user-1",
            access_token="acc", expires_at=timezone.now() + timedelta(hours=1),
        )

    def _call_tool(self, records, fit_payload=None):
        """Подмена вызова инструментов: список, потом ссылка на файл."""
        def side_effect(token, name, arguments=None):
            if name == "querySportRecords":
                return {"structuredContent": {"records": records}}
            return {"structuredContent": fit_payload or {}}
        return side_effect

    @mock.patch("integrations.coros.call_tool")
    def test_poll_imports_new_workouts(self, m_tool):
        m_tool.side_effect = self._call_tool([_record()])
        result = poll_coros(self.account.pk)
        self.assertEqual(result, "новых тренировок: 1")
        w = ExternalWorkout.objects.get(user_id=self.uid, source="coros")
        self.assertEqual(w.distance_m, 6000)
        self.assertEqual(w.trust_level, "medium", "без файла — середина, а не отказ")

    @mock.patch("integrations.coros.call_tool")
    def test_known_workout_is_not_downloaded_again(self, m_tool):
        """Лимит у них 50 файлов в сутки: уже взятую тренировку не перекачиваем."""
        m_tool.side_effect = self._call_tool([_record()])
        poll_coros(self.account.pk)
        m_tool.reset_mock()
        m_tool.side_effect = self._call_tool([_record()])
        poll_coros(self.account.pk)
        names = [c.args[1] for c in m_tool.call_args_list]
        self.assertEqual(names, ["querySportRecords"], "полез за файлом повторно")

    @mock.patch("integrations.coros._request", return_value=(b"fit", {}))
    @mock.patch("integrations.fit.parse")
    @mock.patch("integrations.coros.call_tool")
    def test_real_recording_is_trusted(self, m_tool, m_parse, m_req):
        m_tool.side_effect = self._call_tool(
            [_record()], fit_payload={"url": "https://files.coros.com/a-1.fit"})
        m_parse.return_value = _recorded_track()
        poll_coros(self.account.pk)
        w = ExternalWorkout.objects.get(user_id=self.uid)
        self.assertEqual(w.trust_level, "high")
        self.assertGreater(w.track_points, 50)

    @mock.patch("integrations.coros._request", return_value=(b"fit", {}))
    @mock.patch("integrations.fit.parse")
    @mock.patch("integrations.coros.call_tool")
    def test_drawn_track_is_flagged(self, m_tool, m_parse, m_req):
        m_tool.side_effect = self._call_tool(
            [_record()], fit_payload={"url": "https://files.coros.com/a-1.fit"})
        m_parse.return_value = _drawn_track()
        poll_coros(self.account.pk)
        w = ExternalWorkout.objects.get(user_id=self.uid)
        self.assertEqual(w.trust_level, "low")
        self.assertTrue(w.flagged)

    @mock.patch("integrations.coros.call_tool")
    def test_record_without_distance_is_skipped(self, m_tool):
        m_tool.side_effect = self._call_tool([{"labelId": "x", "sportType": "run"}])
        self.assertEqual(poll_coros(self.account.pk), "новых тренировок: 0")
        self.assertEqual(ExternalWorkout.objects.count(), 0)

    def test_poll_without_account_does_nothing(self):
        self.assertEqual(poll_coros(999999), "нет аккаунта")

    @mock.patch("integrations.tasks.poll_coros.delay")
    def test_scheduled_run_covers_every_connected_account(self, m_delay):
        self.assertEqual(poll_coros_all(), "поставлено опросов: 1")
        m_delay.assert_called_once_with(self.account.pk)

    @mock.patch("integrations.coros.refresh_tokens",
                return_value={"access_token": "new-acc", "expires_in": 3600})
    @mock.patch("integrations.coros.call_tool")
    def test_expired_token_is_refreshed(self, m_tool, m_refresh):
        m_tool.side_effect = self._call_tool([])
        self.account.expires_at = timezone.now() - timedelta(minutes=1)
        self.account.refresh_token = "ref"
        self.account.save(update_fields=["expires_at", "refresh_token"])
        poll_coros(self.account.pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.access_token, "new-acc")


class CorosPayloadTests(ApiTestCase):
    """Форма ответа у них плавает — разбор не должен быть хрупким."""

    phone = "+79990009403"

    def test_tool_payload_reads_structured_and_text(self):
        self.assertEqual(
            coros.tool_payload({"structuredContent": {"a": 1}}), {"a": 1})
        self.assertEqual(
            coros.tool_payload({"content": [{"type": "text", "text": '{"b": 2}'}]}), {"b": 2})
        self.assertIsNone(coros.tool_payload({}))

    def test_sse_answer_is_understood(self):
        raw = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        self.assertEqual(coros._parse_rpc(raw)["result"], {"ok": True})

    def test_pkce_pair_matches_the_standard(self):
        import base64
        import hashlib
        verifier, challenge = coros.make_pkce()
        digest = hashlib.sha256(verifier.encode()).digest()
        self.assertEqual(challenge, base64.urlsafe_b64encode(digest).decode().rstrip("="))
