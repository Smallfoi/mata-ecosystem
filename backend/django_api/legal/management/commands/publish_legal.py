"""Публикует юридические документы экосистемы из docs/legal/*.md в БД.

В отличие от seed_legal_drafts (создаёт ЧЕРНОВИКИ-заглушки), эта команда:
  1. читает реальные тексты из docs/legal/*.md;
  2. подставляет реквизиты оператора из ОКРУЖЕНИЯ (на проде — из Lockbox через .env),
     поэтому ПДн/реквизиты НЕ хранятся в публичном репозитории;
  3. создаёт LegalDocument (тип+версия) и ПУБЛИКУЕТ (published_at), идемпотентно:
     версия, которая уже есть, не трогается (дальше текст правят в админке).

Новая редакция — только у ИЗМЕНИВШИХСЯ документов. Подняли LEGAL_VERSION, а текст
документа (без строки «Редакция … от …») совпадает с опубликованным — новую версию
не создаём: иначе каждый пользователь заново принимал бы неизменённые обязательные
документы (согласие привязано к конкретной версии). Посмотреть заранее, что выйдет:
`publish_legal --check` — ничего не пишет.

После публикации приложения и сайт тянут актуальные версии по GET /v1/legal/documents.

Безопасность деплоя: если обязательные реквизиты в окружении НЕ заданы (например, dev),
команда НИЧЕГО не публикует и не падает — просто сообщает и выходит. Так её можно
безопасно вызывать из cloud-init/деплоя.

Реквизиты из окружения:
  LEGAL_OPERATOR   — «Индивидуальный предприниматель Фамилия Имя Отчество»
  LEGAL_OGRNIP     — ОГРНИП
  LEGAL_INN        — ИНН
  LEGAL_ADDRESS    — адрес оператора
  LEGAL_EMAIL      — контактный e-mail
  LEGAL_PHONE      — контактный телефон
  LEGAL_SITE       — домен сайта (по умолч. mata-club.ru)
  LEGAL_AGE        — возрастной порог (по умолч. 18)
  LEGAL_VERSION    — версия редакции (по умолч. 1.0); менять при существенных правках
  LEGAL_DATE       — дата редакции (по умолч. сегодня, ДД.ММ.ГГГГ)
"""
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from legal.models import LegalDocument

# (doc_type, заголовок, обязателен ли к принятию, файл в docs/legal/)
DOCS = [
    ("terms", "Пользовательское соглашение", True, "01-terms.md"),
    ("privacy", "Политика конфиденциальности", True, "02-privacy.md"),
    ("pd_consent", "Согласие на обработку персональных данных", True, "03-pd-consent.md"),
    ("marketing", "Согласие на рекламные рассылки", False, "04-marketing-consent.md"),
    ("offer", "Публичная оферта (Store)", True, "05-offer.md"),
    ("loyalty", "Правила программы лояльности", True, "06-loyalty-rules.md"),
    ("club", "Правила сообщества и клубов", True, "07-community-rules.md"),
    ("competition", "Правила соревнований и наград", False, "08-competition-rules.md"),
    ("delivery", "Доставка и получение заказа", False, "09-delivery.md"),
    ("returns", "Возврат и обмен", False, "10-returns.md"),
    ("distribution", "Согласие на распространение персональных данных (ст. 10.1)", False, "11-distribution-consent.md"),
    ("contacts", "Контакты", False, "12-contacts.md"),
]

# Обязательные реквизиты — без них не публикуем.
REQUIRED_ENV = ["LEGAL_OPERATOR", "LEGAL_OGRNIP", "LEGAL_INN", "LEGAL_EMAIL", "LEGAL_PHONE"]


def _docs_dir():
    if os.environ.get("LEGAL_DOCS_DIR"):
        return Path(os.environ["LEGAL_DOCS_DIR"])
    # backend/django_api -> корень репозитория -> docs/legal
    return Path(settings.BASE_DIR).parent.parent / "docs" / "legal"


# Подстановки, которые меняются от редакции к редакции, — при сравнении текста с
# опубликованным на их месте может стоять что угодно.
_EDITION = ("[ВЕРСИЯ]", "[ДАТА]")


def _requisites():
    return {
        "[ОПЕРАТОР]": os.environ.get("LEGAL_OPERATOR", ""),
        "[ОГРН/ОГРНИП]": os.environ.get("LEGAL_OGRNIP", ""),
        "[ОГРНИП]": os.environ.get("LEGAL_OGRNIP", ""),
        "[ОГРН]": os.environ.get("LEGAL_OGRNIP", ""),
        "[ИНН]": os.environ.get("LEGAL_INN", ""),
        "[ЮР.АДРЕС]": os.environ.get("LEGAL_ADDRESS", ""),
        "[АДРЕС]": os.environ.get("LEGAL_ADDRESS", ""),
        "[EMAIL]": os.environ.get("LEGAL_EMAIL", ""),
        "[ТЕЛЕФОН]": os.environ.get("LEGAL_PHONE", ""),
        "[САЙТ]": os.environ.get("LEGAL_SITE", "mata-club.ru"),
        "[ВОЗРАСТ]": os.environ.get("LEGAL_AGE", "18"),
    }


def _fill(text, repl):
    for k, v in repl.items():
        if v:
            text = text.replace(k, v)
    return text


def _subst(text):
    ver = os.environ.get("LEGAL_VERSION", "1.0")
    date = os.environ.get("LEGAL_DATE") or timezone.now().strftime("%d.%m.%Y")
    return _fill(text, {**_requisites(), "[ВЕРСИЯ]": ver, "[ДАТА]": date}), ver


def same_text(raw, published):
    """Текст шаблона совпадает с опубликованным, не считая версии и даты редакции?

    Сравниваем построчно: в строке шаблона реквизиты подставлены, а на месте
    [ВЕРСИЯ]/[ДАТА] — любая строка. Пустые строки и отступы по краям не важны.
    Изменились реквизиты в окружении — текст другой, это тоже новая редакция.
    """
    repl = _requisites()
    tpl = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    pub = [ln.strip() for ln in (published or "").splitlines() if ln.strip()]
    if len(tpl) != len(pub):
        return False
    edition = re.compile("|".join(re.escape(t) for t in _EDITION))
    for t, p in zip(tpl, pub):
        pattern = ".*?".join(re.escape(_fill(part, repl)) for part in edition.split(t))
        if not re.fullmatch(pattern, p):
            return False
    return True


class Command(BaseCommand):
    help = "Публикует юр-документы из docs/legal/*.md в БД (реквизиты — из окружения)."

    def add_arguments(self, parser):
        parser.add_argument("--drafts", action="store_true",
                            help="Не публиковать (только создать/обновить как черновики).")
        parser.add_argument("--check", action="store_true",
                            help="Только показать, какие документы получат новую редакцию; "
                                 "ничего не записывать.")

    def handle(self, *args, **options):
        missing_env = [k for k in REQUIRED_ENV if not os.environ.get(k)]
        if missing_env:
            self.stdout.write(self.style.WARNING(
                "Реквизиты в окружении не заданы (%s) — публикация пропущена. "
                "На проде они приходят из Lockbox; локально это нормально." % ", ".join(missing_env)
            ))
            return

        docs_dir = _docs_dir()
        publish = not options["drafts"]
        check = options["check"]
        now = timezone.now()
        published, skipped, leftovers = 0, 0, {}
        unchanged, changed = [], []

        for doc_type, title, required, fname in DOCS:
            path = docs_dir / fname
            if not path.exists():
                self.stdout.write(self.style.WARNING("нет файла %s — пропуск" % fname))
                continue
            raw = path.read_text(encoding="utf-8")
            body, ver = _subst(raw)
            # Оставшиеся незаполненные [плейсхолдеры] — сообщим (но не блокируем).
            # Ссылки между документами — «[Политика](02-privacy.md)» — не заглушки.
            left = sorted(set(re.findall(r"\[[^\]\n]{1,40}\](?!\()", body)))
            if left:
                leftovers[fname] = left

            existing = LegalDocument.objects.filter(doc_type=doc_type, version=ver).first()
            if existing is not None:
                # Эта версия уже есть — НЕ трогаем: после первичной публикации источник
                # правды — АДМИНКА (владелец правит текст там; авто-деплой не должен
                # затирать правки). Чтобы выкатить новый текст из .md — поднять LEGAL_VERSION.
                skipped += 1
                continue
            last = (LegalDocument.objects.filter(doc_type=doc_type, published_at__isnull=False)
                    .order_by("-published_at").first())
            if last is not None and same_text(raw, last.body):
                # Текст не менялся — остаётся действующая редакция, повторное
                # согласие пользователей не нужно.
                unchanged.append("%s (%s)" % (fname, last.version))
                continue
            changed.append("%s (%s → %s)" % (fname, last.version if last else "—", ver))
            if check:
                continue
            LegalDocument.objects.create(
                doc_type=doc_type, version=ver, title=title,
                is_required=required, body=body,
                published_at=now if publish else None,
            )
            if publish:
                published += 1

        if check:
            self.stdout.write("Проверка, версия %s — ничего не записано." % os.environ.get("LEGAL_VERSION", "1.0"))
            self.stdout.write("Получат новую редакцию: %s" % (", ".join(changed) or "нет"))
            self.stdout.write("Без изменений, остаётся прежняя: %s" % (", ".join(unchanged) or "нет"))
            self.stdout.write("Уже есть в этой версии (правится в админке): %d" % skipped)
            return
        if unchanged:
            self.stdout.write("Без изменений, остаётся прежняя редакция: %s" % ", ".join(unchanged))
        self.stdout.write(self.style.SUCCESS(
            "Юр-документы: %s %d шт., пропущено (уже есть, правится в админке) %d (версия %s)." % (
                "опубликовано" if publish else "черновики", published, skipped,
                os.environ.get("LEGAL_VERSION", "1.0"),
            )
        ))
        if leftovers:
            self.stdout.write(self.style.WARNING("Остались незаполненные плейсхолдеры:"))
            for fname, left in leftovers.items():
                self.stdout.write("  %s: %s" % (fname, ", ".join(left)))
