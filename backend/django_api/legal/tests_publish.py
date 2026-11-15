"""publish_legal: новая редакция — только у изменившихся документов.

Согласие привязано к конкретной версии документа, поэтому выпуск новой версии
неизменённого обязательного документа заставил бы каждого пользователя принимать
его заново. Проверяем на временном каталоге с двумя документами.
"""
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from legal.management.commands import publish_legal as cmd
from legal.models import LegalDocument

TERMS = """# Пользовательское соглашение

> Редакция `[ВЕРСИЯ]` от `[ДАТА]`.

1. Оператор — `[ОПЕРАТОР]`, ИНН `[ИНН]`.
2. Обращения: `[EMAIL]`.
"""

LOYALTY_OLD = """# Правила программы лояльности

> Редакция `[ВЕРСИЯ]` от `[ДАТА]`.

1. Баллы начисляются за бег.
"""

LOYALTY_NEW = LOYALTY_OLD + "2. Бонусы сгорают через 12 месяцев.\n"

ENV = {
    "LEGAL_OPERATOR": "ИП Тестов Т.Т.",
    "LEGAL_OGRNIP": "300000000000000",
    "LEGAL_INN": "140000000000",
    "LEGAL_EMAIL": "hello@example.ru",
    "LEGAL_PHONE": "+70000000000",
}


class PublishOnlyChangedTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self._write("01-terms.md", TERMS)
        self._write("06-loyalty-rules.md", LOYALTY_OLD)
        docs = [d for d in cmd.DOCS if d[0] in ("terms", "loyalty")]
        patcher = mock.patch.object(cmd, "DOCS", docs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, name, text):
        (self.dir / name).write_text(text, encoding="utf-8")

    def _run(self, version, date, *args, **extra):
        env = {**ENV, **extra, "LEGAL_DOCS_DIR": str(self.dir), "LEGAL_VERSION": version, "LEGAL_DATE": date}
        out = StringIO()
        with mock.patch.dict(os.environ, env):
            call_command("publish_legal", *args, stdout=out)
        return out.getvalue()

    def _versions(self, doc_type):
        return sorted(LegalDocument.objects.filter(doc_type=doc_type).values_list("version", flat=True))

    def test_first_publication_creates_every_document(self):
        self._run("1.2", "28.09.2026")
        self.assertEqual(self._versions("terms"), ["1.2"])
        self.assertEqual(self._versions("loyalty"), ["1.2"])
        body = LegalDocument.objects.get(doc_type="terms").body
        self.assertIn("Редакция `1.2` от `28.09.2026`", body)
        self.assertIn("ИП Тестов Т.Т.", body)

    def test_new_version_only_for_changed_document(self):
        self._run("1.2", "28.09.2026")
        self._write("06-loyalty-rules.md", LOYALTY_NEW)
        out = self._run("1.3", "20.11.2026")
        self.assertEqual(self._versions("loyalty"), ["1.2", "1.3"])
        self.assertEqual(self._versions("terms"), ["1.2"], "неизменённое соглашение не переиздаём")
        self.assertIn("01-terms.md (1.2)", out)
        current = {d.doc_type: d.version for d in LegalDocument.current()}
        self.assertEqual(current, {"terms": "1.2", "loyalty": "1.3"})

    def test_check_writes_nothing_and_lists_changes(self):
        self._run("1.2", "28.09.2026")
        self._write("06-loyalty-rules.md", LOYALTY_NEW)
        out = self._run("1.3", "20.11.2026", "--check")
        self.assertIn("06-loyalty-rules.md (1.2 → 1.3)", out)
        self.assertIn("01-terms.md (1.2)", out)
        self.assertEqual(self._versions("loyalty"), ["1.2"])

    def test_changed_requisites_make_a_new_edition(self):
        self._run("1.2", "28.09.2026")
        self._run("1.3", "20.11.2026", LEGAL_EMAIL="new@example.ru")
        self.assertEqual(self._versions("terms"), ["1.2", "1.3"])

    def test_admin_edits_of_existing_version_are_kept(self):
        self._run("1.2", "28.09.2026")
        LegalDocument.objects.filter(doc_type="terms").update(body="правка юриста в админке")
        self._run("1.2", "28.09.2026")
        self.assertEqual(LegalDocument.objects.get(doc_type="terms").body, "правка юриста в админке")

    def test_same_text_ignores_blank_lines_and_edition_line(self):
        published = "\n\n".join([
            "# Пользовательское соглашение",
            "> Редакция `1.0` от `01.01.2026`.",
            "1. Оператор — `ИП Тестов Т.Т.`, ИНН `140000000000`.",
            "2. Обращения: `hello@example.ru`.",
        ])
        with mock.patch.dict(os.environ, ENV):
            self.assertTrue(cmd.same_text(TERMS, published))
            self.assertFalse(cmd.same_text(TERMS, published.replace("Обращения", "Жалобы")))
