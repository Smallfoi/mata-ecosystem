"""Адрес клиента для лимитов и журналов (аудит D03)."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from common.clientip import client_ip
from common.throttling import AuthEndpointThrottle


def _req(**meta):
    return SimpleNamespace(META=meta)


class ClientIpTests(SimpleTestCase):
    def test_real_ip_from_our_proxy_is_used(self):
        # nginx в сети compose (172.16/12) передаёт адрес клиента в X-Real-IP.
        self.assertEqual(client_ip(_req(REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="203.0.113.9")),
                         "203.0.113.9")

    def test_forwarded_for_is_never_used(self):
        r = _req(REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="203.0.113.9",
                 HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9")
        self.assertEqual(client_ip(r), "203.0.113.9")
        # Без X-Real-IP — адрес соединения, а не то, что клиент написал в XFF.
        self.assertEqual(client_ip(_req(REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4")),
                         "172.18.0.5")

    def test_header_from_untrusted_peer_is_ignored(self):
        self.assertEqual(client_ip(_req(REMOTE_ADDR="198.51.100.7", HTTP_X_REAL_IP="203.0.113.9")),
                         "198.51.100.7")

    def test_garbage_header_is_ignored(self):
        self.assertEqual(client_ip(_req(REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="1.2.3.4, 5.6.7.8")),
                         "172.18.0.5")
        self.assertEqual(client_ip(_req(REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="<script>")),
                         "172.18.0.5")

    def test_no_address_at_all(self):
        self.assertEqual(client_ip(_req()), "unknown")

    def test_throttles_use_the_same_source(self):
        r = _req(REMOTE_ADDR="172.18.0.5", HTTP_X_REAL_IP="203.0.113.9",
                 HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.9")
        self.assertEqual(AuthEndpointThrottle().get_ident(r), "203.0.113.9")
