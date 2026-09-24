"""Проверка данных каталога: находит то, что похоже на опечатку.

Примеры — с боевого каталога. Главный реальный случай: у артикула FRTM010 три
позиции названы женскими, а одна мужской. Сервер такое принимает молча, и ошибка
живёт на витрине, пока её случайно не заметят.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog import audit
from catalog.models import CheckDismissal, Product
from common.testutils import login_admin
from staff.models import StaffProfile

PAGE = "/admin/data-check/"


def make(pid, name, **extra):
    data = dict(id=pid, name=name, category_id="c1", price=3990)
    data.update(extra)
    product = Product.objects.create(**data)
    product.rebuild_display_name()
    product.save(update_fields=["display_name", "model_key"])
    return product


class ChecksTests(TestCase):
    def test_gender_mismatch_is_found(self):
        """FRTM010: три женских и одна мужская — меньшинство и есть опечатка."""
        for i in range(3):
            make(f"g{i}", f"Футболка женская BMAI {i}", article="FRTM010-1")
        odd = make("g-odd", "Футболка мужская BMAI", article="FRTM010-2")

        found = audit.check_gender_mismatch(list(Product.objects.all()))
        self.assertEqual(len(found), 1)
        self.assertIn("FRTM010", found[0]["title"])
        self.assertEqual([p.id for p in found[0]["products"]], [odd.id])

    def test_same_gender_is_not_reported(self):
        for i in range(3):
            make(f"ok{i}", f"Футболка женская BMAI {i}", article="FRTM011-1")
        self.assertEqual(audit.check_gender_mismatch(list(Product.objects.all())), [])

    def test_strange_size_is_found(self):
        """«3.5» у шорт — это длина, а не размер (реальный случай)."""
        make("s1", "Шорты мужские BMAI", article="FRSM020-1", sizes=["3.5"])
        make("s2", "Шорты мужские BMAI", article="FRSM020-1", sizes=["M"])
        make("s3", "Носки MATA", article="FRNM001-1", sizes=["39-41"])

        found = audit.check_strange_size(list(Product.objects.all()))
        self.assertEqual(len(found), 1, "нормальные размеры не должны попадать в находки")
        self.assertIn("3.5", found[0]["title"])

    def test_colour_mismatch_is_found(self):
        make("c1", "Футболка мужская BMAI ЧЕРНЫЙ", article="FRTM012-1", colors=["БЕЛЫЙ"])
        make("c2", "Футболка мужская BMAI ЧЕРНЫЙ", article="FRTM012-2", colors=["ЧЕРНЫЙ"])

        found = audit.check_color_mismatch(list(Product.objects.all()))
        self.assertEqual(len(found), 1)
        self.assertIn("БЕЛЫЙ", found[0]["title"])

    def test_bad_article_is_found(self):
        make("a1", "Майка BMAI", article="ФРТМ 013")
        make("a2", "Майка BMAI", article="FRTM013-1")
        found = audit.check_bad_article(list(Product.objects.all()))
        self.assertEqual(len(found), 1)

    def test_duplicate_variant_is_found(self):
        make("d1", "Жилет женский BMAI", article="FRWK006-1", sizes=["L"], colors=["ЧЕРНЫЙ"])
        make("d2", "Жилет женский BMAI", article="FRWK006-1", sizes=["L"], colors=["ЧЕРНЫЙ"])
        found = audit.check_duplicate_variant(list(Product.objects.all()))
        self.assertEqual(len(found), 1)
        self.assertIn("FRWK006", found[0]["title"])

    def test_price_gap_is_found(self):
        """Лишний ноль в цене: 3 990 и 39 900 в одной модели."""
        make("p1", "Шорты мужские BMAI", article="FRSM021-1", price=3990)
        make("p2", "Шорты мужские BMAI", article="FRSM021-2", price=39900)
        found = audit.check_price_differs(list(Product.objects.all()))
        self.assertEqual(len(found), 1)

    def test_clean_catalog_reports_nothing(self):
        make("n1", "Футболка женская BMAI", article="FRTM014-1", sizes=["M"], colors=["ЧЕРНЫЙ"])
        make("n2", "Футболка женская BMAI", article="FRTM014-1", sizes=["L"], colors=["ЧЕРНЫЙ"])
        sections = audit.run_all()
        self.assertEqual(sum(s["total"] for s in sections), 0)


class DataCheckPageTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("owner_dc", "dc@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_dc", "OwnerPass!2026")

    def test_page_shows_findings_with_links(self):
        for i in range(3):
            make(f"pg{i}", f"Футболка женская BMAI {i}", article="FRTM015-1")
        make("pg-odd", "Футболка мужская BMAI", article="FRTM015-2")

        r = self.client.get(PAGE)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.context["found"], 1)
        self.assertContains(r, "FRTM015")
        self.assertContains(r, "/admin/catalog/product/pg-odd/change/")

    def test_clean_catalog_says_so(self):
        make("pg-ok", "Футболка женская BMAI", article="FRTM016-1", sizes=["M"],
             colors=["ЧЕРНЫЙ"])
        r = self.client.get(PAGE)
        self.assertEqual(r.context["found"], 0)
        self.assertContains(r, "Подозрительного не нашлось")

    def test_tab_permission_required(self):
        staff = get_user_model().objects.create_user("clerk_dc", "c@t.dev", "ClerkPass!2026",
                                                     is_staff=True)
        StaffProfile.objects.create(user=staff, full_name="Кладовщик")
        other = self.client_class()
        login_admin(other, "clerk_dc", "ClerkPass!2026")
        self.assertNotEqual(other.get(PAGE).status_code, 200)


class DismissTests(TestCase):
    """«Проверено, не ошибка»: замечание уходит, но возвращается, если данные менялись."""

    def setUp(self):
        get_user_model().objects.create_superuser("owner_dis", "di@t.dev", "OwnerPass!2026")
        login_admin(self.client, "owner_dis", "OwnerPass!2026")
        for i in range(3):
            make(f"dz{i}", f"Футболка женская BMAI {i}", article="FRTM020-1")
        self.odd = make("dz-odd", "Футболка мужская BMAI", article="FRTM020-2")

    def _item_url(self):
        return "/admin/data-check/item/?check=gender&key=FRTM020"

    def _gender_found(self):
        """Сколько замечаний именно по полу: на этих данных срабатывает не только
        проверка пола, поэтому общий счётчик тут ничего не скажет."""
        page = self.client.get("/admin/data-check/")
        section = next(s for s in page.context["sections"] if s["id"] == "gender")
        return section["total"], page

    def test_detail_page_shows_positions(self):
        r = self.client.get(self._item_url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Футболка мужская BMAI")
        self.assertContains(r, "/admin/catalog/product/dz-odd/change/")

    def test_dismiss_hides_the_finding(self):
        self.client.post("/admin/data-check/item/",
                         {"check": "gender", "key": "FRTM020", "note": "так и надо"})
        self.assertEqual(CheckDismissal.objects.count(), 1)

        total, page = self._gender_found()
        self.assertEqual(total, 0, "закрытое замечание всё ещё показывается")
        self.assertEqual(page.context["dismissed"], 1)

    def test_finding_returns_when_data_changes(self):
        """Закрываем КОНКРЕТНОЕ состояние: правка данных возвращает замечание."""
        self.client.post("/admin/data-check/item/", {"check": "gender", "key": "FRTM020"})
        self.assertEqual(self._gender_found()[0], 0)

        odd = Product.objects.get(pk="dz-odd")
        odd.name = "Футболка мужская BMAI новая"
        odd.save(update_fields=["name"])

        self.assertEqual(self._gender_found()[0], 1,
                         "данные изменились — замечание обязано вернуться")

    def test_closed_page_can_restore(self):
        self.client.post("/admin/data-check/item/", {"check": "gender", "key": "FRTM020"})
        row = CheckDismissal.objects.get()
        self.client.post("/admin/data-check/closed/", {"id": row.pk})
        self.assertEqual(CheckDismissal.objects.count(), 0)
        self.assertEqual(self._gender_found()[0], 1)

    def test_fixed_finding_just_disappears(self):
        """Исправили в 1С — замечание пропадает само, без кнопок."""
        odd = Product.objects.get(pk="dz-odd")
        odd.name = "Футболка женская BMAI исправленная"
        odd.rebuild_display_name()
        odd.save(update_fields=["name", "display_name", "model_key"])
        self.assertEqual(self._gender_found()[0], 0)

    def test_unknown_check_is_404(self):
        self.assertEqual(self.client.get("/admin/data-check/item/?check=нет&key=x").status_code,
                         404)

