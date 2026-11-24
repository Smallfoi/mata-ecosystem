"""Куда уходят вызовы OpenAI с этого сервера — и доходят ли.

Зачем отдельная команда. Генерация фото ломается не в коде, а в дороге: OpenAI
отказывает российским адресам (`unsupported_country_region_territory`) ещё до
проверки ключа, поэтому прод ходит через релей вне РФ. Когда «не работает
генерация», настоящих вопросов три: есть ли ключ, какой адрес API, и не стоит ли
поверх него прокси. Ответ живёт в `.env`, читать который снаружи нельзя — там
секреты. Команда отвечает на все три, не показывая ни ключа, ни секретного пути
релея, и потому разрешена в канале `ops-shell.sh`.

Запуск (канал Claude):  ssh … ubuntu@<прод> "manage photo_route"
"""
import os
import socket
import urllib.parse

from django.core.management.base import BaseCommand

from productmedia import providers

DIRECT_HOST = "api.openai.com"
_TIMEOUT = 6


def _reachable(host: str, port: int):
    """Открывается ли TCP-соединение. Не проверяет ни ключ, ни ответ API —
    только то, что адрес вообще существует и слушает."""
    try:
        with socket.create_connection((host, port), timeout=_TIMEOUT):
            return True, ""
    except Exception as e:  # noqa: BLE001 — любое падение здесь это «не доехали»
        return False, str(e)[:120]


class Command(BaseCommand):
    help = "Показать маршрут вызовов OpenAI (ключ/адрес/прокси) и его доступность."

    def handle(self, *args, **options):
        w = self.stdout.write

        w("Ключ OPENAI_API_KEY: %s" % ("есть" if providers.openai_enabled() else "НЕТ"))

        base = providers.base_url()
        u = urllib.parse.urlsplit(base)
        host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
        # У релея путь — это пропуск, его прятать обязательно. У обычного адреса
        # путь всего лишь «/v1», и прятать его значит пугать на ровном месте.
        path = u.path.strip("/")
        shown = "" if not path else ("/" + path if path == "v1" else "/…(путь скрыт)")
        w("Адрес API: %s://%s%s" % (u.scheme, u.netloc, shown))
        if host == DIRECT_HOST:
            w("  напрямую в OpenAI — из РФ это отказ по стране, нужен релей")
        else:
            w("  через релей (не api.openai.com) — так и задумано")

        proxy = (os.environ.get("OPENAI_PROXY") or "").strip()
        p = urllib.parse.urlsplit(proxy) if proxy else None
        w("Прокси OPENAI_PROXY: %s" % (f"{p.hostname}:{p.port or 8888}" if p else "не задан"))

        ok_base, err_base = _reachable(host, port) if host else (False, "адрес не разобран")
        w("Связь с адресом API: %s%s" % ("есть" if ok_base else "НЕТ",
                                         "" if ok_base else f" ({err_base})"))
        ok_proxy = True
        if p and p.hostname:
            ok_proxy, err_proxy = _reachable(p.hostname, p.port or 8888)
            w("Связь с прокси: %s%s" % ("есть" if ok_proxy else "НЕТ",
                                        "" if ok_proxy else f" ({err_proxy})"))

        w("")
        if not providers.openai_enabled():
            w("ИТОГ: без ключа генерация не пойдёт — OPENAI_API_KEY пуст.")
        elif p and not ok_proxy:
            # Главная ловушка: прокси применяется ко ВСЕМ вызовам (providers._open),
            # включая вызовы через живой релей. Мёртвый прокси рубит рабочую дорогу.
            w("ИТОГ: прокси задан и НЕ отвечает. Он применяется ко всем вызовам, "
              "в том числе через релей, — поэтому падает всё. Уберите OPENAI_PROXY "
              "из Lockbox `mata-eco-image`, обновите .env и перезапустите web и worker.")
        elif p and host != DIRECT_HOST:
            w("ИТОГ: заданы и релей, и прокси. Запрос пойдёт через прокси — релей "
              "в обход. Если прокси больше не нужен, уберите OPENAI_PROXY.")
        elif host == DIRECT_HOST and not p:
            w("ИТОГ: вызовы идут прямо в OpenAI. Из РФ это отказ по стране — "
              "задайте OPENAI_BASE_URL на релей.")
        elif not ok_base:
            w("ИТОГ: адрес API не отвечает — релей выключен или сменился адрес.")
        else:
            w("ИТОГ: маршрут на месте. Если генерация всё равно падает, причина "
              "дальше дороги — ключ, баланс или ответ модели; смотрите photo_test.")
