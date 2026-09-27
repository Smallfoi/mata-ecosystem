"""Браузерный smoke сайта (аудит F06): витрина рисуется из API в настоящем Chromium.

Что проверяет: статика сайта (`САЙТ МАТА/`) открывается в headless-браузере, каталог
берёт товары из API и рисует карточку, фильтры строятся по категориям из API, на
странице нет необработанных JS-ошибок. Ловит то, что `node --check` не видит:
ошибку во время выполнения, сломанный порядок скриптов, изменившийся контракт
`/v1/models` на стороне сайта.

API подменяется (Playwright `route`): бэкенд не нужен, ответы стабильны. Сайт на
127.0.0.1 сам ходит в `http://127.0.0.1:8000/v1` (dev-режим catalog.js/boot.js) —
эти запросы и перехватываем. Внешние CDN (GSAP, Lenis, шрифты) отрезаны: проверка
не зависит от сети и заодно показывает, что витрина живёт без них.

Запуск:  pip install playwright==1.63.0 && python -m playwright install chromium
         python tools/site_smoke.py
Локально можно взять установленный Chrome: SMOKE_CHROME_CHANNEL=chrome.
"""
import functools
import http.server
import json
import os
import sys
import threading
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "САЙТ МАТА"
API_PREFIX = "http://127.0.0.1:8000/v1"

MODEL = {
    "key": "smoke-model",
    "name": "Кроссовки Smoke",
    "brand": "МАТА",
    "categoryId": "smoke-shoes",
    "price": 4490,
    "oldPrice": None,
    "imageUrl": "",
    "thumbUrl": "",
    "description": "Карточка из подменённого API",
    "sizes": ["41", "42"],
    "inStock": True,
    "colors": [{
        "name": "ЧЕРНЫЙ", "inStock": True, "photos": [],
        "sizes": [{"size": "41", "productId": "smoke-41", "price": 4490, "inStock": True},
                  {"size": "42", "productId": "smoke-42", "price": 4490, "inStock": True}],
    }],
}
CATEGORIES = [{"id": "all", "name": "Все"}, {"id": "smoke-shoes", "name": "Обувь Smoke"}]


def _api(route):
    """Ответы подменённого API. Неизвестное — 404: сайт обязан это переживать."""
    path = route.request.url[len(API_PREFIX):].split("?")[0]
    body = {"/models": [MODEL], "/categories": CATEGORIES}.get(path)
    if body is None:
        return route.fulfill(status=404, content_type="application/json",
                             body='{"detail": "not mocked"}',
                             headers={"Access-Control-Allow-Origin": "*"})
    return route.fulfill(status=200, content_type="application/json",
                         body=json.dumps(body, ensure_ascii=False),
                         headers={"Access-Control-Allow-Origin": "*"})


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main() -> int:
    handler = functools.partial(_Quiet, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"

    errors, api_calls = [], []
    with sync_playwright() as p:
        channel = os.environ.get("SMOKE_CHROME_CHANNEL") or None
        browser = p.chromium.launch(headless=True, channel=channel)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route_all(route):
            url = route.request.url
            if url.startswith(API_PREFIX):
                api_calls.append(url[len(API_PREFIX):])
                return _api(route)
            if url.startswith(origin):
                return route.continue_()
            return route.abort()  # внешние CDN/шрифты/сбор ошибок — вне проверки

        page.route("**/*", route_all)
        page.goto(origin + "/index.html", wait_until="domcontentloaded")

        problems = []
        name = price = ""
        cards_total = 0
        card = page.locator('[data-product-grid] .product-card[data-id="smoke-model"]')
        try:
            card.wait_for(state="attached", timeout=15000)
            name = card.locator("h3").inner_text().strip()
            price = card.locator(".product-price").inner_text()
            cards_total = page.locator("[data-product-grid] .product-card").count()
        except PlaywrightTimeout:
            problems.append("карточка из API не появилась в сетке каталога за 15 с")
        try:
            page.locator('[data-filters] [data-filter="smoke-shoes"]').wait_for(
                state="attached", timeout=5000)
        except PlaywrightTimeout:
            problems.append("фильтр категории из /v1/categories не появился")
        browser.close()
    server.shutdown()

    if problems:
        pass  # карточки нет — сравнивать её поля бессмысленно
    elif name != MODEL["name"]:
        problems.append(f"название карточки «{name}», ждали «{MODEL['name']}»")
    elif "4" not in price or "490" not in price:
        problems.append(f"цена карточки «{price}», ждали 4 490 ₽")
    elif cards_total != 1:
        problems.append(f"карточек в сетке {cards_total}, ждали 1 (из API)")
    if not any(c.startswith("/models") for c in api_calls):
        problems.append("витрина не запросила /v1/models")
    if errors:
        problems.append("JS-ошибки на странице: " + " | ".join(errors[:5]))

    print("API-запросы сайта:", ", ".join(sorted(set(c.split("?")[0] for c in api_calls))))
    if problems:
        print("SMOKE FAIL:\n  - " + "\n  - ".join(problems))
        return 1
    print(f"SMOKE OK: карточка «{name}» ({price.strip()}), фильтр категорий из API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
