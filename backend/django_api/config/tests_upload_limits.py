"""Лимит nginx на загрузку не должен быть меньше лимита Django (21.11.2026).

Сотрудники грузили в «Фото товаров» снимки по 11–14 МБ: Django принимал до 12 МБ,
а nginx резал всё больше 8 МБ ответом 413 — HTML-страницей вместо JSON, и экран
писал «сеть не ответила». Человек не видел причины и решил, что упал интернет.
Тест читает тот самый конфиг, из которого автодеплой собирает боевой.
"""
import os
import re
from pathlib import Path

from django.test import SimpleTestCase

from config import product_photos_view

NGINX = Path(__file__).resolve().parents[2] / "nginx" / "mata.conf.example"


def _mb(value: str) -> int:
    value = value.lower()
    if value.endswith("m"):
        return int(value[:-1]) * 1024 * 1024
    if value.endswith("k"):
        return int(value[:-1]) * 1024
    return int(value)


def _location_limit(conf: str, location: str) -> int:
    block = re.search(r"location\s+" + re.escape(location) + r"\s*\{(.*?)\}", conf, re.S)
    assert block, f"в {NGINX.name} нет location {location}"
    size = re.search(r"client_max_body_size\s+(\w+);", block.group(1))
    assert size, f"у location {location} нет своего client_max_body_size"
    return _mb(size.group(1))


class PhotoUploadLimitTests(SimpleTestCase):
    def test_nginx_lets_through_what_django_accepts(self):
        # В dev-контейнер смонтирован только django_api — там конфига нет. На CI
        # (полный checkout, CI=true) пропуск недопустим: страж молчал бы.
        if not NGINX.exists() and not os.environ.get("CI"):
            self.skipTest("конфиг nginx вне контейнера")
        conf = NGINX.read_text(encoding="utf-8")
        nginx = _location_limit(conf, "= /admin/photos/")
        # Запас на обёртку multipart (поля формы, границы) — хотя бы мегабайт.
        self.assertGreaterEqual(nginx, product_photos_view.MAX_BYTES + 1024 * 1024)

    def test_camera_photo_fits(self):
        # Самый крупный снимок из отказов 21.11.2026 — 13,6 МБ.
        self.assertGreater(product_photos_view.MAX_BYTES, 14 * 1024 * 1024)
