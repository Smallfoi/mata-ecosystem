# -*- coding: utf-8 -*-
"""Проверка настройки Suunto на сервере — без показа самих ключей.

Ключи лежат в Lockbox и попадают в окружение; прочитать их значения ни агенту,
ни по ограниченному каналу нельзя — и правильно. Но знать, доехали ли они до
сервера, нужно: без этого «подключение не работает» и «ключи не положили»
выглядят одинаково.

Команда печатает только факт наличия и длину — по длине видно, не вставили ли
обрезанное значение.

    python manage.py suunto_check
"""
from django.core.management.base import BaseCommand

from integrations import suunto


def _mask(value: str) -> str:
    if not value:
        return "НЕТ"
    return f"есть, {len(value)} символов"


class Command(BaseCommand):
    help = "Показывает, настроено ли подключение Suunto (без значений ключей)"

    def handle(self, *args, **opts):
        self.stdout.write("SUUNTO_CLIENT_ID:        " + _mask(suunto.client_id()))
        self.stdout.write("SUUNTO_CLIENT_SECRET:    " + _mask(suunto.client_secret()))
        self.stdout.write("SUUNTO_SUBSCRIPTION_KEY: " + _mask(suunto.subscription_key()))
        self.stdout.write("Адрес возврата:          " + suunto.redirect_uri())
        if suunto.configured():
            self.stdout.write("\nГотово: подключение Suunto можно предлагать людям.")
        else:
            self.stdout.write(
                "\nНе хватает ключей — подключение отвечает 503. "
                "Положите их в Lockbox и выполните deploy/refresh-env.sh."
            )
