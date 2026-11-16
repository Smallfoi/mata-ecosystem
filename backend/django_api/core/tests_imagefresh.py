"""Сторож свежести образа: разбор requirements и список недостающих пакетов.

Проверки чистые — без docker и без установки пакетов: «что установлено»
передаётся списком. Иначе тест сторожа сам зависел бы от того, свежий ли образ,
то есть падал бы ровно тогда, когда должен срабатывать сторож.
"""
from django.test import SimpleTestCase

from common import checks, imagefresh

SAMPLE = """\
# комментарий целой строкой
Django>=5.2.16,<6.0
psycopg[binary]>=3.1
sentry-sdk[django]>=2.0  # хвостовой комментарий
cryptography>=46  # приехало с Play Integrity

-r dev-requirements.txt
--hash=sha256:deadbeef
some-pkg @ https://example.test/pkg.whl
old-python-only==1.0 ; python_version < "3.10"
"""


class RequirementNames(SimpleTestCase):
    def test_reads_names_without_versions_and_extras(self):
        self.assertEqual(
            imagefresh.required_names(SAMPLE),
            ["Django", "psycopg", "sentry-sdk", "cryptography"],
        )

    def test_skips_flags_urls_and_environment_markers(self):
        """Строки, которые законно могут быть не установлены, сторож не трогает.

        Пакет под старый Python (маркер окружения) на этой машине отсутствует
        правильно; ссылка и флаги pip — вообще не имена пакетов.
        """
        names = imagefresh.required_names(SAMPLE)
        for skipped in ("old-python-only", "some-pkg", "-r", "--hash"):
            self.assertNotIn(skipped, names)


class MissingPackages(SimpleTestCase):
    def test_names_exactly_what_is_absent(self):
        installed = ["Django", "psycopg", "sentry-sdk"]
        self.assertEqual(
            imagefresh.missing(imagefresh.required_names(SAMPLE), installed),
            ["cryptography"],
        )

    def test_silent_when_everything_is_installed(self):
        installed = ["Django", "psycopg", "sentry-sdk", "cryptography"]
        self.assertEqual(imagefresh.missing(imagefresh.required_names(SAMPLE), installed), [])


class CheckMessage(SimpleTestCase):
    def test_warning_names_the_missing_package_and_the_command(self):
        """Главное требование: сторож говорит, ЧЕГО не хватает.

        Прошлый раз причина («нет cryptography») была видна только в трейсбеке
        одного из шести упавших тестов, и шесть красных выглядели как сломанный код.
        """
        def stale():
            return ["cryptography"]

        real, imagefresh.stale_report = imagefresh.stale_report, stale
        try:
            found = checks.image_matches_requirements(None)
        finally:
            imagefresh.stale_report = real

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, checks.W_STALE_IMAGE)
        self.assertIn("cryptography", found[0].msg)
        self.assertIn("--build", found[0].hint)
        # Сообщение говорит про ОКРУЖЕНИЕ — это всё, что проверка знает. Про образ —
        # только подсказка: в живом контейнере пакет мог быть доставлен руками.
        self.assertIn("Окружение", found[0].msg)
        self.assertIn("recreate", found[0].hint)

    def test_quiet_on_a_fresh_image(self):
        def fresh():
            return []

        real, imagefresh.stale_report = imagefresh.stale_report, fresh
        try:
            self.assertEqual(checks.image_matches_requirements(None), [])
        finally:
            imagefresh.stale_report = real

    def test_real_requirements_file_parses_into_known_packages(self):
        """Файл проекта читается, и в нём узнаются настоящие зависимости.

        Защита от тихой поломки разбора: если регулярка перестанет находить имена,
        сторож будет всегда молчать — и это молчание выглядело бы как «всё хорошо».
        """
        names = imagefresh.required_names(imagefresh.REQUIREMENTS.read_text(encoding="utf-8"))
        self.assertIn("Django", names)
        self.assertIn("cryptography", names)
        self.assertGreater(len(names), 10)
