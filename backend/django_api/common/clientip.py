"""Адрес клиента для лимитов и журналов — ОДИН источник на весь бэкенд (аудит D03).

Как устроено на проде: наружу открыт только nginx, Django (`web`) слушает внутри сети
compose (`expose`, не `ports`). Поэтому `REMOTE_ADDR` у Django — всегда адрес самого
nginx, а настоящий адрес клиента nginx передаёт в `X-Real-IP` (ставит `$remote_addr`,
ПЕРЕЗАПИСЫВАЯ то, что прислал клиент).

Чем было плохо раньше: лимиты DRF (`common/throttling.py`) брали адрес штатным
`get_ident`, а он без `NUM_PROXIES` склеивает ВЕСЬ `X-Forwarded-For` в ключ. nginx
этот заголовок ДОПИСЫВАЕТ (`$proxy_add_x_forwarded_for`), значит первая часть — то,
что прислал сам клиент. Меняя её на каждом запросе, клиент получал новый ключ лимита
и перебирал пароли без ограничений. Журнал действий сотрудников брал первый элемент
того же заголовка — туда тоже можно было записать любой адрес.

Правило теперь:
- `X-Real-IP` учитываем, только если запрос пришёл от доверенного прокси (адрес
  соединения из частных сетей/loopback — так выглядит nginx в сети compose). Запрос
  «снаружи» напрямую (такого на проде нет, но на всякий случай) идентифицируется по
  адресу соединения, что бы он ни прислал в заголовках;
- в заголовке должен быть корректный IP — мусор не становится ключом;
- `X-Forwarded-For` не используем вовсе.
"""
import ipaddress

# Сети, из которых приходит наш собственный прокси: docker-сеть compose (172.16/12),
# прочие частные диапазоны и loopback (тест-клиент Django, локальный запуск).
_TRUSTED_PROXY_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)


def _parse_ip(value):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _is_trusted_proxy(ip) -> bool:
    return ip is not None and any(ip in net for net in _TRUSTED_PROXY_NETS)


def client_ip(request) -> str:
    """Адрес клиента: `X-Real-IP` от нашего nginx, иначе адрес соединения."""
    meta = getattr(request, "META", {}) or {}
    remote = _parse_ip(meta.get("REMOTE_ADDR"))
    if _is_trusted_proxy(remote):
        real = _parse_ip(meta.get("HTTP_X_REAL_IP"))
        if real is not None:
            return str(real)
    return str(remote) if remote is not None else "unknown"
