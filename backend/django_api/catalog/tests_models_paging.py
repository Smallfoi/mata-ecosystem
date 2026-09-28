"""Бюджет ответа витрины `/v1/models` (аудит F01).

На проде 27.09.2026 список отдавал 208 карточек (780 складских позиций) одним
ответом ~190 КБ без сжатия. Уже выпущенные сборки Store и сайт читают его
целиком, поэтому без параметров ответ обязан остаться прежним. Новое — только
по запросу:

* `?limit=&offset=` — страница карточек; общее число — в заголовке `X-Total-Count`;
* ETag + `If-None-Match` → 304 (повторный заход не качает список заново);
* gzip, если клиент его принимает.

Бюджет: число запросов к БД не зависит от числа моделей (2 — позиции + фото).
"""
import gzip
import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.models import Product, ProductPhoto
from catalog.tests_models_api import make

# Бюджет запросов к БД на один ответ списка: позиции + фото. Не растёт с каталогом.
QUERY_BUDGET = 2


def make_models(count, start=0):
    """`count` разных моделей по два размера — как одежда в 1С."""
    for i in range(start, start + count):
        for size in ("S", "M"):
            make(f"m{i}{size}", f"Футболка арт.FRTS{i:03d}-1 р.{size}",
                 article=f"FRTS{i:03d}-1", sizes=[size], colors=["ЧЕРНЫЙ"],
                 stock_count=3, sort=i)


class ModelListCompatibilityTests(TestCase):
    """Без параметров — прежний ответ: весь список массивом."""

    def setUp(self):
        make_models(5)

    def test_no_params_gives_whole_list_as_array(self):
        r = self.client.get("/v1/models")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, list, "старые сборки ждут массив")
        self.assertEqual(len(body), 5)
        self.assertEqual(r["X-Total-Count"], "5")

    def test_empty_limit_is_ignored(self):
        """`?limit=` без значения — как без параметра (не отбиваем 400)."""
        self.assertEqual(len(self.client.get("/v1/models?limit=").json()), 5)


class ModelListPagingTests(TestCase):
    def setUp(self):
        make_models(7)

    def _keys(self, url):
        return [c["key"] for c in self.client.get(url).json()]

    def test_page_is_a_slice_of_the_whole_list(self):
        whole = self._keys("/v1/models")
        self.assertEqual(self._keys("/v1/models?limit=3"), whole[:3])
        self.assertEqual(self._keys("/v1/models?limit=3&offset=3"), whole[3:6])
        self.assertEqual(self._keys("/v1/models?limit=3&offset=6"), whole[6:])
        self.assertEqual(self._keys("/v1/models?limit=3&offset=30"), [])

    def test_pages_do_not_lose_models(self):
        """Обход страницами даёт ровно те же карточки — ни одна не теряется."""
        whole = self._keys("/v1/models")
        seen, offset = [], 0
        for _ in range(len(whole) + 2):     # страховка от вечного цикла
            page = self._keys(f"/v1/models?limit=2&offset={offset}")
            if not page:
                break
            seen += page
            offset += 2
        self.assertEqual(seen, whole)

    def test_page_card_keeps_all_its_sizes(self):
        """Режем по МОДЕЛЯМ, а не по позициям: размеры модели не делятся между страницами."""
        card = self.client.get("/v1/models?limit=1").json()[0]
        self.assertEqual(card["sizes"], ["S", "M"])
        self.assertEqual(card["variantCount"], 2)

    def test_total_count_header(self):
        r = self.client.get("/v1/models?limit=2&offset=2")
        self.assertEqual(r["X-Total-Count"], "7")
        self.assertEqual(r["X-Limit"], "2")
        self.assertEqual(r["X-Offset"], "2")

    def test_total_respects_filters(self):
        r = self.client.get("/v1/models?limit=1&q=FRTS001")
        self.assertEqual(r["X-Total-Count"], "1")

    def test_page_param(self):
        """`page` (с 1) — для тех, кому удобнее страницы, чем смещение."""
        whole = self._keys("/v1/models")
        self.assertEqual(self._keys("/v1/models?limit=3&page=2"), whole[3:6])

    def test_limit_is_capped(self):
        from catalog.models_api import MAX_PAGE_LIMIT
        make_models(MAX_PAGE_LIMIT, start=100)
        r = self.client.get("/v1/models?limit=100000")
        self.assertEqual(len(r.json()), MAX_PAGE_LIMIT)
        self.assertEqual(r["X-Limit"], str(MAX_PAGE_LIMIT))

    def test_bad_params_are_rejected(self):
        for q in ("limit=abc", "limit=0", "limit=-1", "limit=2&offset=-1",
                  "limit=2&page=0", "offset=x"):
            self.assertEqual(self.client.get(f"/v1/models?{q}").status_code, 400, q)

    def test_cors_exposes_total(self):
        """Сайт ходит с другого домена — без Expose-Headers браузер спрячет заголовок."""
        r = self.client.get("/v1/models?limit=1", HTTP_ORIGIN="https://mata-club.ru")
        exposed = r.get("Access-Control-Expose-Headers", "")
        self.assertIn("X-Total-Count", exposed)


class ModelListQueryBudgetTests(TestCase):
    """Число запросов к БД не растёт вместе с каталогом."""

    def _photos(self, n):
        for i in range(n):
            ProductPhoto.objects.create(model_key=f"FRTS{i:03d}", color="ЧЕРНЫЙ",
                                        order=0, image=f"uploads/photos/x{i}.webp",
                                        thumb=f"uploads/photos/x{i}-t.webp")

    def test_budget_does_not_grow_with_models(self):
        make_models(3)
        self._photos(3)
        with self.assertNumQueries(QUERY_BUDGET):
            self.client.get("/v1/models")
        make_models(40, start=3)
        self._photos(43)
        with self.assertNumQueries(QUERY_BUDGET):
            self.client.get("/v1/models")
        with self.assertNumQueries(QUERY_BUDGET):
            self.client.get("/v1/models?limit=5&offset=10")

    def test_page_fetches_photos_only_for_its_models(self):
        make_models(10)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/v1/models?limit=2")
        photo_sql = [q["sql"] for q in ctx.captured_queries
                     if ProductPhoto._meta.db_table in q["sql"]]
        self.assertEqual(len(photo_sql), 1)
        self.assertIn("FRTS000", photo_sql[0])
        self.assertNotIn("FRTS005", photo_sql[0], "страница тянет фото всего каталога")


class ModelListTransportTests(TestCase):
    def setUp(self):
        make_models(6)

    def test_etag_and_not_modified(self):
        r = self.client.get("/v1/models")
        etag = r.get("ETag")
        self.assertTrue(etag, "нет ETag")
        again = self.client.get("/v1/models", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")

    def test_etag_changes_with_catalog(self):
        etag = self.client.get("/v1/models")["ETag"]
        Product.objects.filter(pk="m0S").update(price=1)
        r = self.client.get("/v1/models", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(r.status_code, 200)

    def test_gzip_when_accepted(self):
        plain = self.client.get("/v1/models")
        self.assertNotEqual(plain.get("Content-Encoding"), "gzip",
                            "без Accept-Encoding сжимать нельзя")
        r = self.client.get("/v1/models", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(r.get("Content-Encoding"), "gzip")
        self.assertEqual(json.loads(gzip.decompress(r.content)), plain.json())
