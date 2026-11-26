"""Страницы сайта mata-club.ru, которые отдаёт сервер (аудит 25.11.2026, пункт 1).

У товара свой адрес `/product/<slug>/`: им делятся, его находят Яндекс и Google,
«назад» в браузере закрывает товар, а не уводит с сайта. Страница — та же главная
(`САЙТ МАТА/index.html`), только в шапку подставлены название, описание, картинка
и разметка Product для поисковиков, а в `<noscript>` — текст товара. Браузер
покупателя открывает поверх главной окно этого товара (script.js).

Мессенджеры и поисковики JavaScript не выполняют, поэтому всё, что им нужно
(title, og:*, JSON-LD), обязано прийти с сервера, а не дорисовываться в браузере.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponsePermanentRedirect

SITE_ORIGIN = "https://mata-club.ru"

_TR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def slugify_ru(text: str) -> str:
    """«Кроссовки ANTA WALK 3.0» → «krossovki-anta-walk-3-0»."""
    low = (text or "").lower()
    out = "".join(_TR.get(ch, ch) for ch in low)
    out = re.sub(r"[^a-z0-9]+", "-", out)
    return out.strip("-")


def model_slug(name: str, key: str) -> str:
    """Адрес модели: название + ключ модели. Ключ держит адрес уникальным, название
    делает его читаемым. Если ключ уже есть в названии («ANTA WALK 2.0»), не дублируем."""
    n, k = slugify_ru(name), slugify_ru(key)
    if not k:
        return n
    if not n:
        return k
    if f"-{k}-" in f"-{n}-":
        return n
    return f"{n}-{k}"


def _key_suffix_match(slug: str, cards: list) -> dict | None:
    """Название в 1С поменяли — адрес изменился. Старую ссылку узнаём по ключу в конце."""
    for card in cards:
        k = slugify_ru(card["key"])
        if k and (slug == k or slug.endswith("-" + k)):
            return card
    return None


def _visible_cards(request):
    """Витрина сайта как её видит покупатель: только опубликованное и не снятое в 1С,
    в порядке сайта. Черновики (превью Конструктора) поисковикам не отдаём."""
    from .models import Product
    from .models_api import build_cards

    qs = Product.objects.filter(is_published=True, is_active_1c=True)
    cards, _ = build_cards(qs.order_by("sort_site", "sort", "id"))
    return cards


# ── Текст для шапки страницы ─────────────────────────────────────────────────────
_SECTION = re.compile(r"^(технологии|посадка и размер|кому подойд[её]т|частые вопросы|"
                      r"характеристики)\s*:?\s*$", re.I)


def _summary(description: str, name: str, limit: int = 180) -> str:
    """Первые предложения описания без заголовков разделов паспорта — для meta description."""
    lines = [ln.strip() for ln in (description or "").splitlines() if ln.strip()]
    body = [ln for ln in lines if not _SECTION.match(ln) and ln.lower() != (name or "").lower()]
    text = " ".join(body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-")
        text = cut + "…"
    return text


def _abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return "https://api.mata-club.ru" + (url if url.startswith("/") else "/" + url)


def _price_text(value) -> str:
    try:
        return f"{int(round(float(value))):,}".replace(",", " ") + " ₽"
    except (TypeError, ValueError):
        return ""


def _json_ld(card: dict, url: str, image: str, summary: str) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": card["name"],
        "url": url,
        "sku": card["key"],
        "description": summary or card["name"],
        "offers": {
            "@type": "Offer",
            "url": url,
            "priceCurrency": "RUB",
            "price": f"{float(card.get('price') or 0):.0f}",
            "availability": "https://schema.org/InStock" if card.get("inStock")
            else "https://schema.org/OutOfStock",
            "itemCondition": "https://schema.org/NewCondition",
        },
    }
    if image:
        data["image"] = [image]
    if card.get("brand"):
        data["brand"] = {"@type": "Brand", "name": card["brand"]}
    if card.get("reviewCount"):
        data["aggregateRating"] = {"@type": "AggregateRating",
                                   "ratingValue": card.get("rating") or 0,
                                   "reviewCount": card["reviewCount"]}
    # «</script>» внутри названия не должен закрыть тег разметки.
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _site_index() -> str | None:
    path = Path(getattr(settings, "SITE_DIR", "/site")) / "index.html"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _set_meta(page: str, pattern: str, replacement: str) -> str:
    new, n = re.subn(pattern, lambda _m: replacement, page, count=1, flags=re.S)
    return new if n else page


def render_product(page: str, card: dict, url: str) -> str:
    """Подставить в главную шапку и текст товара. Шаблон — живой index.html сайта:
    правки вёрстки не надо повторять в двух местах."""
    e = lambda s: html.escape(s or "", quote=True)  # noqa: E731
    name = card["name"] or ""
    summary = _summary(card.get("description") or "", name)
    price = _price_text(card.get("price"))
    title = f"{name} — купить в МАТА" + (f" за {price}" if price else "")
    desc = summary or f"{name} в магазине МАТА: размеры и цвета в наличии, доставка по России."
    image = _abs(card.get("cardUrl") or card.get("imageUrl") or "")

    # <base> — первым в <head>: страница живёт по адресу /product/…/, а все ссылки
    # главной относительные (styles.css, media/…). Без него браузер искал бы
    # /product/…/styles.css.
    head = (f'<base href="/" />\n    <link rel="canonical" href="{e(url)}" />\n'
            f'    <script>window.MATA_ROUTE = {{"product": {json.dumps(card["key"], ensure_ascii=False)}}};'
            f"</script>\n"
            f'    <script type="application/ld+json">{_json_ld(card, url, image, summary)}</script>')
    if image:
        # Главное фото страницы товара — первым в очереди загрузки (LCP).
        head += f'\n    <link rel="preload" as="image" href="{e(image)}" fetchpriority="high" />'
    page = page.replace("<head>", "<head>\n    " + head, 1)
    # Страница товара (владелец 26.11): с первого кадра — товар, а не главная.
    # Скрипт снимет класс, когда откроет товар (или покажет главную, если его нет).
    page = page.replace('<html lang="ru">', '<html lang="ru" class="route-product">', 1)
    page = page.replace('<img data-pv-img src="" alt=""',
                        f'<img data-pv-img src="{e(image)}" alt="{e(name)}"', 1)
    page = page.replace('<h1 class="pv-title" data-pv-name></h1>',
                        f'<h1 class="pv-title" data-pv-name>{e(name)}</h1>', 1)
    page = page.replace('<span class="pv-price" data-pv-price></span>',
                        f'<span class="pv-price" data-pv-price>{e(price)}</span>', 1)
    page = _set_meta(page, r"<title>.*?</title>", f"<title>{e(title)}</title>")
    page = _set_meta(page, r'<meta\s+name="description"\s+content="[^"]*"\s*/>',
                     f'<meta name="description" content="{e(desc)}" />')
    page = _set_meta(page, r'<meta property="og:type" content="[^"]*" />',
                     '<meta property="og:type" content="product" />')
    page = _set_meta(page, r'<meta property="og:title" content="[^"]*" />',
                     f'<meta property="og:title" content="{e(name)}" />')
    page = _set_meta(page, r'<meta\s+property="og:description"\s+content="[^"]*"\s*/>',
                     f'<meta property="og:description" content="{e(desc)}" />')
    page = _set_meta(page, r'<meta name="twitter:title" content="[^"]*" />',
                     f'<meta name="twitter:title" content="{e(name)}" />')
    page = _set_meta(page, r'<meta\s+name="twitter:description"\s+content="[^"]*"\s*/>',
                     f'<meta name="twitter:description" content="{e(desc)}" />')
    if image:
        page = _set_meta(page, r'<meta property="og:image" content="[^"]*" />',
                         f'<meta property="og:image" content="{e(image)}" />\n'
                         f'    <meta property="og:url" content="{e(url)}" />')
        page = _set_meta(page, r'<meta name="twitter:image" content="[^"]*" />',
                         f'<meta name="twitter:image" content="{e(image)}" />')

    # Текст товара для тех, кто страницу не исполняет (поисковик без JS, читалка).
    noscript = (
        '<noscript><article class="ssr-product">'
        f"<p>{e(card.get('brand') or '')}</p><h1>{e(name)}</h1>"
        f"<p>{e(price)} · {'В наличии' if card.get('inStock') else 'Нет в наличии'}</p>"
        + (f'<img src="{e(image)}" alt="{e(name)}" width="600" />' if image else "")
        + "".join(f"<p>{e(ln)}</p>" for ln in (card.get("description") or "").splitlines()
                  if ln.strip())
        + '<p><a href="/#catalog">Весь каталог МАТА</a></p></article></noscript>'
    )
    page = page.replace("<body>", "<body>\n    " + noscript, 1)
    return page


def product_page(request, slug: str):
    """`/product/<slug>/` — страница товара (главная + окно этого товара)."""
    slug = (slug or "").strip("/").lower()
    page = _site_index()
    if page is None:
        return HttpResponse("Сайт временно недоступен", status=503,
                            content_type="text/plain; charset=utf-8")
    cards = _visible_cards(request)
    by_slug = {model_slug(c["name"], c["key"]): c for c in cards}
    card = by_slug.get(slug)
    if card is None:
        moved = _key_suffix_match(slug, cards)
        if moved is not None:
            return HttpResponsePermanentRedirect(
                f"/product/{model_slug(moved['name'], moved['key'])}/")
        # Товара нет (снят с витрины): главная с пометкой для поисковика, код 404.
        page = page.replace("<head>", '<head>\n    <base href="/" />\n'
                            '    <meta name="robots" content="noindex" />', 1)
        resp = HttpResponse(page, status=404, content_type="text/html; charset=utf-8")
        resp["Cache-Control"] = "no-cache"
        return resp
    url = f"{SITE_ORIGIN}/product/{slug}/"
    resp = HttpResponse(render_product(page, card, url), content_type="text/html; charset=utf-8")
    # Остатки и цена меняются — браузер переспрашивает, но HTML лёгкий.
    resp["Cache-Control"] = "no-cache"
    return resp


def sitemap(request):
    """`/sitemap.xml` для mata-club.ru: главная, философия и все товары витрины."""
    urls = [f"{SITE_ORIGIN}/", f"{SITE_ORIGIN}/philosophy/"]
    urls += [f"{SITE_ORIGIN}/product/{model_slug(c['name'], c['key'])}/"
             for c in _visible_cards(request)]
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f"  <url><loc>{html.escape(u)}</loc></url>" for u in urls]
    body.append("</urlset>")
    resp = HttpResponse("\n".join(body) + "\n", content_type="application/xml; charset=utf-8")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp
