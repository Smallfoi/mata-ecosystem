"""Страница товара /product/<slug>/ и карта сайта (D-139, аудит 25.11.2026)."""
import json
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from catalog.models import Category, Product
from catalog.site_pages import model_slug, slugify_ru
from catalog.size_charts import gender_of

INDEX = """<!doctype html>
<html lang="ru">
  <head>
    <script src="boot.js?v=1"></script>
    <title>МАТА — интернет-магазин</title>
    <meta
      name="description"
      content="Главная МАТА"
    />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="МАТА" />
    <meta
      property="og:description"
      content="Главная"
    />
    <meta property="og:image" content="media/staw-hero.jpg" />
    <meta name="twitter:title" content="МАТА" />
    <meta
      name="twitter:description"
      content="Главная"
    />
    <meta name="twitter:image" content="media/staw-hero.jpg" />
  </head>
  <body>
    <main id="top"></main>
  </body>
</html>
"""


class SlugTests(SimpleTestCase):
    def test_translit_and_key(self):
        self.assertEqual(slugify_ru("Кроссовки ANTA WALK 3.0"), "krossovki-anta-walk-3-0")
        self.assertEqual(model_slug("Футболка мужская STAW", "26SADT013"),
                         "futbolka-muzhskaya-staw-26sadt013")

    def test_key_already_in_name_is_not_repeated(self):
        self.assertEqual(model_slug("ANTA WALK 2.0", "ANTA WALK 2.0"), "anta-walk-2-0")

    def test_cyrillic_key(self):
        self.assertEqual(model_slug("Очки STRAVA", "ОЧКИ STRAVA (4)"), "ochki-strava-ochki-strava-4")


class GenderTests(SimpleTestCase):
    def test_anta_by_article(self):
        self.assertEqual(gender_of(brand="ANTA", article="812625546-1", name="ANTA WALK"), "men")
        self.assertEqual(gender_of(brand="ANTA", article="862535102-1", name="Футболка"), "women")

    def test_by_name(self):
        self.assertEqual(gender_of(brand="BMAI", article="", name="Кроссовки женские BMAI"), "women")
        self.assertEqual(gender_of(brand="STAW", article="", name="Бафф Унисекс. STAW"), "unisex")
        self.assertEqual(gender_of(brand="ROCKBROS", article="", name="ROCKBROS ДЕТСКИЕ"), "kids")
        self.assertEqual(gender_of(brand="SIS", article="", name="Гель SIS"), "")


class ProductPageTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "index.html").write_text(INDEX, encoding="utf-8")
        self.override = override_settings(SITE_DIR=self.tmp.name)
        self.override.enable()
        Category.objects.create(id="shoes", name="Кроссовки")
        Product.objects.create(
            id="p1", name="ANTA WALK 3.0", brand="ANTA", category_id="shoes", price=9000,
            article="812625546-1", colors=["Серый"], sizes=["42"], model_key="812625546",
            description="ANTA WALK 3.0\nЛёгкие кроссовки для прогулок.\nТехнологии:\nПена.",
            is_published=True)
        Product.objects.create(id="hidden", name="Черновик", brand="ANTA", category_id="shoes",
                               price=1, is_published=False)

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def test_card_has_slug_and_gender(self):
        resp = self.client.get("/v1/models/812625546")
        self.assertEqual(resp.json()["slug"], "anta-walk-3-0-812625546")
        self.assertEqual(resp.json()["gender"], "men")

    def test_product_page_has_seo_head(self):
        resp = self.client.get("/product/anta-walk-3-0-812625546/")
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        # <base> — первым в <head>, иначе относительные boot.js/styles.css уедут в /product/…
        self.assertRegex(page, r"<head>\s*<base href=\"/\" />")
        self.assertLess(page.index("<base"), page.index("boot.js"))
        self.assertIn("<title>ANTA WALK 3.0 — купить в МАТА за 9 000 ₽</title>", page)
        self.assertIn('content="Лёгкие кроссовки для прогулок. Пена."', page)
        self.assertIn('<meta property="og:type" content="product" />', page)
        self.assertIn('<link rel="canonical" href="https://mata-club.ru/product/anta-walk-3-0-812625546/" />',
                      page)
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1))
        self.assertEqual(ld["@type"], "Product")
        self.assertEqual(ld["offers"]["price"], "9000")
        self.assertEqual(ld["brand"]["name"], "ANTA")
        self.assertIn('"product": "812625546"', page)
        self.assertIn("<noscript>", page)

    def test_old_slug_redirects_by_key(self):
        resp = self.client.get("/product/staroe-nazvanie-812625546/")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], "/product/anta-walk-3-0-812625546/")

    def test_unknown_and_unpublished_give_404_noindex(self):
        for slug in ("net-takogo", "chernovik-hidden"):
            resp = self.client.get(f"/product/{slug}/")
            self.assertEqual(resp.status_code, 404, slug)
            self.assertIn('name="robots" content="noindex"', resp.content.decode())

    def test_sitemap_lists_published_products(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("<loc>https://mata-club.ru/product/anta-walk-3-0-812625546/</loc>", body)
        self.assertNotIn("chernovik", body)

    def test_title_is_escaped(self):
        Product.objects.filter(id="p1").update(name='Кеды "<script>"')
        resp = self.client.get("/product/kedy-script-812625546/")
        page = resp.content.decode()
        self.assertNotIn('"<script>"', page.split("</head>")[0].replace('"product"', ""))
        self.assertIn("&lt;script&gt;", page)


@override_settings(SITE_DIR="/nonexistent-site-dir")
class NoSiteTests(TestCase):
    def test_missing_site_gives_503(self):
        self.assertEqual(self.client.get("/product/x/").status_code, 503)
