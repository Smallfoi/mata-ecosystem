"""Списки админки не должны дорожать с каждой строкой (N+1).

19.11.2026: «Баллы» на 100 строк делали 113 запросов — колонка «Пользователь»
искала аккаунт отдельно на каждую строку; «Категории» на две строки — 51 запрос:
выпадающий список группы в каждой строке тянул вкладку для каждого пункта.
Сторож: число запросов на странице одинаково при 3 и при 30 строках.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import Account
from catalog.models import Category, ShowcaseGroup, ShowcaseTab
from common.testutils import login_admin
from loyalty.models import LoyaltyTransaction


class AdminListQueryTests(TestCase):

    def setUp(self):
        get_user_model().objects.create_superuser("owner_q", "o@q.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_q", "OwnerPass!2026")

    def _queries(self, url):
        with CaptureQueriesContext(connection) as q:
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return len(q.captured_queries)

    def _transactions(self, start, n):
        for i in range(start, start + n):
            Account.objects.create(id=f"uq{i}", name=f"Бегун {i}", phone=f"+7999100{i:04d}",
                                   email=f"uq{i}@q.dev")
            LoyaltyTransaction.objects.create(id=f"tq{i}", user_id=f"uq{i}", amount=10,
                                              source="run")
            # Строка удалённого аккаунта: её «удалён» тоже не должен стоить запроса.
            LoyaltyTransaction.objects.create(id=f"tg{i}", user_id=f"gone{i}", amount=5,
                                              source="run")

    def test_user_column_costs_one_query_per_page(self):
        url = "/admin/loyalty/loyaltytransaction/"
        self._transactions(0, 3)
        few = self._queries(url)
        self._transactions(3, 27)
        many = self._queries(url)
        self.assertEqual(many, few, "запросов стало больше вместе со строками — N+1")

    def test_user_column_still_shows_name_and_deleted(self):
        self._transactions(0, 1)
        html = self.client.get("/admin/loyalty/loyaltytransaction/").content.decode()
        self.assertIn("Бегун 0", html)
        self.assertIn("gone0 (удалён)", html)

    def test_category_group_picker_does_not_query_per_option(self):
        url = "/admin/catalog/category/"
        tab = ShowcaseTab.objects.create(id="qtab", name="Проверка")
        for i in range(6):
            ShowcaseGroup.objects.create(id=f"qg{i}", tab=tab, name=f"Группа {i}", sort=i)
        Category.objects.create(id="qc0", name="Кроссовки")
        Category.objects.create(id="qc1", name="Шиповки")
        few = self._queries(url)
        for i in range(2, 12):
            Category.objects.create(id=f"qc{i}", name=f"Категория {i}")
        many = self._queries(url)
        self.assertEqual(many, few, "запросов стало больше вместе со строками — N+1")


class DashboardAnalyticsTests(TestCase):
    """Главная админки: воронка активации и удержание когорт (D-30) видны владельцу."""

    def setUp(self):
        from django.core.cache import cache

        cache.delete("dashboard:analytics:v1")
        get_user_model().objects.create_superuser("owner_d", "o@d.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_d", "OwnerPass!2026")

    def test_funnel_and_retention_on_dashboard(self):
        Account.objects.create(id="ud1", name="Новичок", phone="+79991110001", email="ud1@d.dev")
        html = self.client.get("/admin/").content.decode()
        self.assertIn("Воронка активации", html)
        self.assertIn("Первый забег", html)
        self.assertIn("Удержание по неделям", html)

    def test_broken_analytics_does_not_break_dashboard(self):
        from unittest.mock import patch

        with patch("analytics.retention.weekly_cohorts", side_effect=RuntimeError("boom")):
            r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Удержание по неделям", r.content.decode())
