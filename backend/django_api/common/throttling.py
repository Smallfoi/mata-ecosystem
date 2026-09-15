"""Rate-limiting (P0 безопасность). Аутентификация у нас своя (JWT в common.security),
поэтому стандартный UserRateThrottle по request.user не работает — ключуемся по `sub`
из токена. Неаутентифицированные — по IP. Вход/регистрация — отдельный жёсткий лимит
(анти-брутфорс кода/пароля).

**Лимит зависит от НАЗНАЧЕНИЯ эндпоинта, а не от одного общего потолка (D-36).** Витрина
(каталог, баннеры, контент сайта) — дешёвое публичное чтение: 1 запрос к БД, ~14 мс, её
смотрят без входа. Мобильные операторы РФ раздают абонентов через CGNAT: сотни человек за
одним публичным IP, а один просмотр каталога — это 10–20 запросов. Общий лимит для
анонимных отсекал таких гостей (нагрузочный прогон: 98% ответов 429). Поэтому витринное
чтение вынесено в свой щедрый scope `public`, а вход (20/мин) и запись не ослаблены.

Витрину throttle всё равно не защищает от скрейпинга — он обходится сменой адреса; там
работают кэш и CDN (D-31).

Прод: общий кэш (Redis) для счётчиков на нескольких воркерах — см. план D-07."""
from rest_framework.throttling import SimpleRateThrottle

from common.security import user_id_from_request


class UserJWTRateThrottle(SimpleRateThrottle):
    """Лимит на пользователя (по JWT sub). Анонимные — пропускаем (их ловит AnonIP)."""
    scope = "user"

    def get_cache_key(self, request, view):
        uid = user_id_from_request(request)
        if not uid:
            return None
        return self.cache_format % {"scope": self.scope, "ident": uid}


class AnonIPRateThrottle(SimpleRateThrottle):
    """Лимит по IP для НЕаутентифицированных (каталог Store, вход). С токеном — пропускаем
    (чтобы не штрафовать многих пользователей за одним NAT/прокси оператора)."""
    scope = "anon"

    def get_cache_key(self, request, view):
        if user_id_from_request(request):
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AuthEndpointThrottle(SimpleRateThrottle):
    """Жёсткий лимит по IP на /auth (вход/регистрация) — анти-брутфорс."""
    scope = "auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class OtpPollThrottle(SimpleRateThrottle):
    """Опрос канала входа (`phone/channel`) — свой мягкий лимит по IP.

    Жёсткий `auth` (20/мин) сюда не годится: пока человек ждёт код, клиент спрашивает
    канал раз в 3 секунды (20 запросов в минуту на одного), и за мобильным адресом
    оператора таких людей десятки. Запрос дешёвый: ответ провайдера кэшируется на
    пару секунд, поэтому в SIGMA уходит не больше одного обращения на номер.
    """
    scope = "otp_poll"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


# Безопасные методы: не меняют состояние, поэтому лимитируются отдельно от записи.
_SAFE = ("GET", "HEAD", "OPTIONS")


class PublicReadThrottle(SimpleRateThrottle):
    """Витринное чтение (каталог/баннеры/контент/юр-документы) — щедрый лимит по IP.

    Считает ТОЛЬКО безопасные методы: если тот же URL принимает и POST (например,
    отзывы к товару), запись сюда не попадёт и останется под обычными лимитами.
    """
    scope = "public"

    def get_cache_key(self, request, view):
        if request.method not in _SAFE:
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class WriteUserJWTRateThrottle(UserJWTRateThrottle):
    """Пользовательский лимит только для изменяющих запросов (для смешанных вьюх)."""

    def get_cache_key(self, request, view):
        if request.method in _SAFE:
            return None
        return super().get_cache_key(request, view)


class WriteAnonIPRateThrottle(AnonIPRateThrottle):
    """Лимит по IP для анонимных только на запись (для смешанных вьюх)."""

    def get_cache_key(self, request, view):
        if request.method in _SAFE:
            return None
        return super().get_cache_key(request, view)


# Набор для витринных вьюх: чтение — по щедрому `public`, запись на том же URL —
# по обычным лимитам. Вешать как @throttle_classes(PUBLIC_READ).
PUBLIC_READ = [PublicReadThrottle, WriteUserJWTRateThrottle, WriteAnonIPRateThrottle]
