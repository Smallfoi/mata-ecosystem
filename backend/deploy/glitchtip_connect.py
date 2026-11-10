"""Подготовить GlitchTip для МАТА (D-122) — выполняется ВНУТРИ контейнера GlitchTip.

Запускает `deploy/glitchtip.sh connect` через `manage.py shell`. Повторный запуск
безопасен: организацию, команду, проекты и ключи не дублирует, токен для админки
магазина переиспользует.

Печатает строки KEY=VALUE для .env магазина (их забирает glitchtip.sh) и DSN
приложений отдельной строкой APPS_DSN=… (его владелец кладёт в секрет GitHub).
"""
from django.apps import apps
from django.contrib.auth import get_user_model

DOMAIN = "errors.mata-club.ru"
INTERNAL = "glitchtip-web:8000"   # бэкенд магазина шлёт ошибки внутри сети, без DNS и TLS
ORG_SLUG = "mata"
TOKEN_LABEL = "mata-admin-errors"
READ_SCOPES = ["org:read", "project:read", "team:read", "event:read"]

Org = apps.get_model("organizations_ext", "Organization")
Team = apps.get_model("teams", "Team")
Project = apps.get_model("projects", "Project")
ProjectKey = apps.get_model("projects", "ProjectKey")
APIToken = apps.get_model("api_tokens", "APIToken")
OU = apps.get_model("organizations_ext", "OrganizationUser")

user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
if user is None:
    raise SystemExit("НЕТ_ПОЛЬЗОВАТЕЛЯ: сначала glitchtip.sh admin")

# Адрес организации GlitchTip строит из названия, а кириллицу превращает в мусор
# («МАТА» → «-3v»). Поэтому ищем по адресу и, создав, ставим его явно.
org = Org.objects.filter(slug=ORG_SLUG).first()
if org is None:
    org = Org.objects.create(name="МАТА")
    Org.objects.filter(pk=org.pk).update(slug=ORG_SLUG)
    org.refresh_from_db()
if not org.organization_users.filter(user=user).exists():
    org.add_user(user, role=OU._meta.get_field("role").choices[-1][0])   # Owner
team, _ = Team.objects.get_or_create(organization=org, slug="mata")
team.members.add(*org.organization_users.filter(user=user))


def project(slug, platform):
    p, _ = Project.objects.get_or_create(
        organization=org, slug=slug, defaults={"name": slug, "platform": platform})
    team.projects.add(p)
    key = ProjectKey.objects.filter(project=p, is_active=True).first() or \
        ProjectKey.objects.create(project=p)
    return p, str(key.public_key).replace("-", "")


backend, backend_key = project("backend", "python-django")
mobile, mobile_key = project("apps", "flutter")

token = APIToken.objects.filter(user=user, label=TOKEN_LABEL).first()
if token is None:
    # Права только на чтение: админке магазина нужен список ошибок, менять их ей нечего.
    # BitField: бит права = его позиция в списке флагов поля.
    flags = APIToken._meta.get_field("scopes").flags
    value = 0
    for scope in READ_SCOPES:
        value |= 1 << flags.index(scope)
    token = APIToken.objects.create(user=user, label=TOKEN_LABEL, scopes=value)

print(f"ENV:SENTRY_DSN=http://{backend_key}@{INTERNAL}/{backend.id}")
print("ENV:SENTRY_ENVIRONMENT=prod")
print(f"ENV:GLITCHTIP_API_URL=http://{INTERNAL}")
print(f"ENV:GLITCHTIP_WEB_URL=https://{DOMAIN}")
print(f"ENV:GLITCHTIP_API_TOKEN={token.token}")
print(f"ENV:GLITCHTIP_ORG={ORG_SLUG}")
print(f"APPS_DSN=https://{mobile_key}@{DOMAIN}/{mobile.id}")
