# -*- coding: utf-8 -*-
"""Нащупать верные адреса Suunto Cloud API на живом аккаунте.

Зачем команда. Их портал показывает пути только скриптом, а в открытых описаниях
версия указана по-разному: где-то `/v2/workouts`, где-то `/v3/workouts`. Угадывать
в коде нельзя — у Developer API всего **200 запросов в неделю**, и десяток
случайных попыток съест заметную часть недельного запаса.

Команда делает ровно один заход по каждому кандидату, печатает, кто ответил, и
подсказывает, что положить в окружение. Запускать с подключённым аккаунтом.

    python manage.py suunto_probe                 # список тренировок
    python manage.py suunto_probe --workout <id>  # одна тренировка и FIT
"""
from django.core.management.base import BaseCommand

from integrations import suunto
from integrations.models import WatchAccount
from integrations.tasks import _fresh_token

LIST_CANDIDATES = ["/v2/workouts", "/v3/workouts", "/v2/workout", "/v1/workouts"]
ONE_CANDIDATES = ["/v2/workout/{id}", "/v3/workout/{id}", "/v2/workouts/{id}"]
FIT_CANDIDATES = ["/v2/workout/exportFit/{id}", "/v3/workout/exportFit/{id}",
                  "/v2/workouts/{id}/fit"]


class Command(BaseCommand):
    help = "Проверяет, какие адреса Suunto Cloud API отвечают (экономно по запросам)"

    def add_arguments(self, parser):
        parser.add_argument("--user", default="", help="ID пользователя (по умолчанию первый)")
        parser.add_argument("--workout", default="", help="ID тренировки для проверки адресов")

    def handle(self, *args, **opts):
        if not suunto.configured():
            self.stdout.write("Ключи Suunto не заданы — сначала suunto_check.")
            return
        qs = WatchAccount.objects.filter(source="suunto")
        if opts["user"]:
            qs = qs.filter(user_id=opts["user"])
        account = qs.first()
        if account is None:
            self.stdout.write("Нет ни одного подключённого аккаунта Suunto.")
            return
        token = _fresh_token(account)

        def probe(path):
            try:
                data = suunto.api_get(path, token)
            except suunto.SuuntoError as e:
                return f"— {e}"
            if isinstance(data, (bytes, bytearray)):
                return f"ОТВЕТИЛ, файл {len(data)} байт"
            size = len(data) if hasattr(data, "__len__") else "?"
            return f"ОТВЕТИЛ, элементов: {size}"

        self.stdout.write("Список тренировок:")
        for path in LIST_CANDIDATES:
            self.stdout.write(f"  {path:<24} {probe(path)}")

        wid = opts["workout"]
        if not wid:
            self.stdout.write("\nДля проверки адресов одной тренировки и FIT "
                              "повторите с --workout <id> (id виден в списке выше).")
            return

        self.stdout.write("\nОдна тренировка:")
        for tmpl in ONE_CANDIDATES:
            self.stdout.write(f"  {tmpl:<28} {probe(tmpl.format(id=wid))}")
        self.stdout.write("\nFIT-файл:")
        for tmpl in FIT_CANDIDATES:
            self.stdout.write(f"  {tmpl:<28} {probe(tmpl.format(id=wid))}")
        self.stdout.write(
            "\nЧто ответило — то и положить в окружение:\n"
            "  SUUNTO_WORKOUTS_PATH, SUUNTO_WORKOUT_PATH, SUUNTO_FIT_PATH"
        )
