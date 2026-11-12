"""Поток 6 — итоги дня из 1С и выдача Pareta (D-124, паспорт §15, ТЗ ANALYTICS_FOR_PARETA).

Что проверяем: день принимается целиком и заменяется целиком (с прежней версией в
архиве); не сошлись контрольные суммы — день не принят и прежняя версия в силе;
ошибки в строках перечислены; тревога «день не пришёл» звенит только когда её
включили и уже после 06:00 по Якутску; Pareta видит дни и каталог только со своим
токеном, токеном 1С туда не попасть; себестоимость не уходит в журнал обмена.
"""
import copy
from datetime import datetime, timezone as dt_tz

from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.models import Category, Product, ProductBarcode
from integrations import onec_daily
from integrations.models import OneCDay, OneCDayVersion, OneCExchange, ParetaAccess

TOKEN = "test-1c-token"
PARETA = "test-pareta-token"
DAILY = "/v1/integrations/1c/daily"


def _day(date="2026-11-11", sale_sum=10790):
    sale = {"docId": "ЧК-000123", "time": f"{date}T14:32:05+09:00", "channel": "store",
            "sellerId": "000000017", "sellerName": "Иванова А.", "id": "GUID-1",
            "article": "AR-X1", "name": "Кроссовки Air Runner X1", "size": "42", "qty": 1,
            "price": 11990, "discount": 1200, "sum": sale_sum, "costSum": 5400}
    online = dict(sale, docId="ЧК-000124", channel="mata", orderId="МАТА-48271593",
                  sum=11990, discount=0)
    ret = {"docId": "ВЗ-000045", "time": f"{date}T17:05:00+09:00", "channel": "store",
           "id": "GUID-1", "article": "AR-X1", "name": "Кроссовки Air Runner X1",
           "qty": 1, "sum": 8990, "costSum": 5400}
    rec = {"docId": "ПТ-000311", "time": f"{date}T11:00:00+09:00",
           "supplier": "ООО Спортимпорт", "id": "GUID-1", "article": "AR-X1",
           "name": "Кроссовки Air Runner X1", "qty": 12, "costSum": 64800}
    stock = {"id": "GUID-1", "size": "42", "qty": 3, "costSum": 16200}
    return {
        "date": date, "generatedAt": "2026-11-12T01:15:00+09:00",
        "sales": [sale, online], "returns": [ret], "receipts": [rec], "stockEnd": [stock],
        "totals": {"salesLines": 2, "salesQty": 2, "salesSum": sale_sum + 11990,
                   "returnsLines": 1, "returnsSum": 8990,
                   "receiptsLines": 1, "receiptsQty": 12, "stockEndLines": 1},
    }


# 12.11.2026 10:00 по Якутску — «вчера» для потока это 11.11.
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=dt_tz.utc)


@override_settings(INTEGRATION_1C_TOKEN=TOKEN, PARETA_READ_TOKEN=PARETA)
class DailyIntakeTests(TestCase):
    def post(self, body, token=TOKEN):
        return self.client.post(DAILY, body, content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_day_accepted_and_replaced_whole(self):
        r = self.post(_day())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["received"],
                         {"sales": 2, "returns": 1, "receipts": 1, "stockEnd": 1})
        self.assertFalse(r.json()["replaced"])

        fixed = _day(sale_sum=10500)                 # кассир перепровёл чек задним числом
        r = self.post(fixed)
        self.assertTrue(r.json()["replaced"])
        self.assertEqual(r.json()["version"], 2)
        day = OneCDay.objects.get()
        self.assertEqual(day.payload["sales"][0]["sum"], 10500)
        self.assertEqual(OneCDayVersion.objects.get().payload["sales"][0]["sum"], 10790)

    def test_totals_mismatch_keeps_previous_version(self):
        self.post(_day())
        broken = _day(sale_sum=10500)
        broken["totals"]["salesSum"] = 1                 # не сходится с строками
        r = self.post(broken)
        self.assertEqual(r.status_code, 422)
        self.assertIn("salesSum", r.json()["mismatch"])
        self.assertEqual(OneCDay.objects.get().payload["sales"][0]["sum"], 10790)
        self.assertEqual(OneCDay.objects.get().version, 1)

    def test_row_errors_are_listed(self):
        bad = _day()
        del bad["sales"][0]["sellerId"]
        del bad["sales"][1]["orderId"]                   # заказ МАТА без номера
        bad["returns"][0]["qty"] = "1"                   # число строкой
        r = self.post(bad)
        self.assertEqual(r.status_code, 400)
        errors = r.json()["errors"]
        self.assertIn("sales[0]: нет поля sellerId", errors)
        self.assertIn("sales[1]: для заказа МАТА нужно поле orderId", errors)
        self.assertIn("returns[0]: qty — нужно число", errors)
        self.assertFalse(OneCDay.objects.exists())

    def test_empty_day_is_a_day(self):
        empty = {"date": "2026-11-08", "sales": [], "returns": [], "receipts": [],
                 "stockEnd": [], "totals": {k: 0 for k in onec_daily.TOTALS}}
        self.assertEqual(self.post(empty).status_code, 200)

    def test_dates_and_lists_checked(self):
        self.assertEqual(self.post(_day(date="2023-11-03")).status_code, 400)
        self.assertEqual(self.post(_day(date="2099-01-01")).status_code, 400)
        no_list = _day()
        del no_list["receipts"]
        r = self.post(no_list)
        self.assertEqual(r.status_code, 400)
        self.assertIn("receipts", r.json()["detail"])

    def test_token_required_and_pareta_token_cannot_write(self):
        self.assertEqual(self.post(_day(), token="wrong").status_code, 401)
        self.assertEqual(self.post(_day(), token=PARETA).status_code, 401)

    def test_log_has_no_cost(self):
        self.post(_day())
        row = OneCExchange.objects.filter(operation="daily").get()
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.sample["date"], "2026-11-11")
        self.assertNotIn("costSum", str(row.sample) + str(row.errors) + row.detail)


class DailyWatchTests(TestCase):
    def test_quiet_until_enabled(self):
        self.assertFalse(onec_daily.watch_state(NOW)["late"])

    @override_settings(ONEC_DAILY_EXPECTED="1")
    def test_alarm_after_six_yakutsk_only(self):
        before_six = datetime(2026, 11, 11, 20, 30, tzinfo=dt_tz.utc)   # 05:30 12.11 по Якутску
        self.assertFalse(onec_daily.watch_state(before_six)["late"])
        state = onec_daily.watch_state(NOW)
        self.assertTrue(state["late"])
        self.assertEqual(state["yesterday"], "2026-11-11")
        OneCDay.objects.create(date="2026-11-11", payload={}, received_at=NOW)
        self.assertFalse(onec_daily.watch_state(NOW)["late"])

    @override_settings(ONEC_DAILY_EXPECTED="")
    def test_status_endpoint_public_and_200_when_off(self):
        r = self.client.get(DAILY + "/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"expected", "yesterday", "received", "late"})


@override_settings(INTEGRATION_1C_TOKEN=TOKEN, PARETA_READ_TOKEN=PARETA)
class ParetaApiTests(TestCase):
    def get(self, path, token=PARETA):
        return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}")

    def setUp(self):
        for i, d in enumerate(["2026-11-09", "2026-11-10", "2026-11-11"]):
            body = _day(date=d)
            onec_daily.save(body, now=datetime(2026, 11, 12, 0, i, tzinfo=dt_tz.utc))

    def test_only_pareta_token(self):
        self.assertEqual(self.get("/v1/analytics/daily", token=TOKEN).status_code, 401)
        self.assertEqual(self.get("/v1/analytics/catalog", token="").status_code, 401)

    @override_settings(PARETA_READ_TOKEN="")
    def test_off_without_token(self):
        self.assertEqual(self.get("/v1/analytics/daily", token="").status_code, 401)

    def test_days_pages_with_cursor_and_redelivery(self):
        r = self.get("/v1/analytics/daily?limit=2")
        self.assertEqual([d["date"] for d in r.json()["days"]], ["2026-11-09", "2026-11-10"])
        nxt = r.json()["next"]
        r = self.get(f"/v1/analytics/daily?limit=2&cursor={nxt}")
        self.assertEqual([d["date"] for d in r.json()["days"]], ["2026-11-11"])
        self.assertIsNone(r.json()["next"])

        # День перепровели — он снова в выдаче после того же курсора, с новой версией.
        onec_daily.save(_day(date="2026-11-09", sale_sum=10000))
        r = self.get(f"/v1/analytics/daily?cursor={nxt}")
        self.assertEqual([(d["date"], d["version"]) for d in r.json()["days"]],
                         [("2026-11-11", 1), ("2026-11-09", 2)])

    def test_day_payload_as_sent(self):
        r = self.get("/v1/analytics/daily/2026-11-10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["payload"], _day(date="2026-11-10"))
        self.assertEqual(self.get("/v1/analytics/daily/2026-01-01").status_code, 404)
        self.assertTrue(ParetaAccess.objects.filter(path__contains="2026-11-10", rows=5).exists())

    def test_catalog_by_1c_id_with_1c_price_and_hidden_items(self):
        Category.objects.create(id="shoes", name="Обувь")
        p = Product.objects.create(
            id="p1", name="Кроссовки арт. AR-X1 р. 42", display_name="Кроссовки X1",
            category_id="shoes", price=9990, article="AR-X1", external_id="GUID-1",
            sizes=["42", "43"], stock_by_size={"42": 3, "43": 0}, is_published=False,
            from_1c={"price": 11990, "oldPrice": None})
        ProductBarcode.objects.create(product=p, barcode="4601234567890")
        r = self.get("/v1/analytics/catalog")
        item = r.json()["items"][0]
        self.assertEqual(item["id"], "GUID-1")
        self.assertEqual(item["price1c"], 11990)          # не 9990 из Конструктора
        self.assertFalse(item["published"])               # снятые с витрины тоже видны
        self.assertEqual(item["category"], "Обувь")
        self.assertEqual(item["barcodes"], ["4601234567890"])
        self.assertEqual({v["size"]: v["available"] for v in item["variants"]},
                         {"42": 3, "43": 0})
