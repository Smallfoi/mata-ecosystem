"""Аудит A04: удаление и выгрузка аккаунта охватывают ВСЕ данные человека.

Главная защита — `test_registry_covers_every_user_field`: новый модуль с полем
пользователя, забытый в реестре `accounts.userdata`, валит CI. Остальные тесты
создают данные в каждой модели реестра и проверяют, что после удаления от
человека не осталось ничего, кроме обезличенного финансового следа.
"""
import datetime
import json

from django.apps import apps
from django.core.cache import cache
from django.db import connection, models
from django.test import TestCase
from django.utils import timezone

from accounts import userdata
from accounts.models import Account

USER_FIELD_NAMES = {"user_id", "owner_id", "requester_id", "addressee_id", "user"}


def _fill(model, uid, n):
    """Минимальная строка модели: обязательные поля — заглушки, поля пользователя — uid."""
    kwargs = {}
    for f in model._meta.concrete_fields:
        if f.auto_created or isinstance(f, (models.AutoField, models.BigAutoField)):
            continue
        if f.name in ("user_id", "owner_id", "requester_id", "addressee_id"):
            kwargs[f.name] = uid
            continue
        if f.has_default() or f.null or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
            if not f.primary_key:
                continue
        if isinstance(f, models.ForeignKey):
            kwargs[f.name] = _fill(f.related_model, uid, n + 1000)
            continue
        if isinstance(f, models.DateTimeField):
            kwargs[f.name] = timezone.now()
        elif isinstance(f, models.DateField):
            kwargs[f.name] = datetime.date.today()
        elif isinstance(f, (models.IntegerField, models.FloatField, models.DecimalField)):
            kwargs[f.name] = 1
        elif isinstance(f, models.BooleanField):
            kwargs[f.name] = False
        elif isinstance(f, models.JSONField):
            kwargs[f.name] = {}
        else:
            max_len = getattr(f, "max_length", None) or 40
            kwargs[f.name] = f"t{n}_{f.name}"[:max_len]
    if model._meta.label == "friends.Friendship":
        kwargs["addressee_id"] = "u_friend"
    return model.objects.create(**kwargs)


class RegistryCoverage(TestCase):
    def test_registry_covers_every_user_field(self):
        known = {m for _l, m, _f, _p in userdata.MODELS} | set(userdata.EXCLUDED)
        missing = []
        for model in apps.get_models():
            if model._meta.label == "accounts.Account" or not model._meta.managed:
                continue
            names = {f.name for f in model._meta.concrete_fields}
            if names & USER_FIELD_NAMES and model._meta.label not in known:
                missing.append(model._meta.label)
        self.assertEqual(missing, [], "добавьте модели в accounts/userdata.py (MODELS или EXCLUDED)")

    def test_raw_tables_exist(self):
        tables = connection.introspection.table_names()
        for _label, table, _cols in userdata.RAW_TABLES:
            self.assertIn(table, tables)


class EraseEverything(TestCase):
    phone = "+79990004501"

    def setUp(self):
        cache.clear()
        r = self.client.post("/v1/auth/phone/verify",
                             data=json.dumps({"phone": self.phone, "code": "1234"}),
                             content_type="application/json")
        self.token = r.json()["token"]
        self.uid = Account.objects.get(phone=self.phone).id
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        for n, (_label, model_label, _fields, _policy) in enumerate(userdata.MODELS):
            model = userdata._model(model_label)
            if model is None or model_label in ("orders.Order", "clubs.Club"):
                continue
            _fill(model, self.uid, n)
        from orders.models import Order

        checkout = {"name": "Иван", "phone": self.phone, "email": "i@t.dev",
                    "street": "Ленина", "house": "1", "deliveryType": "courier"}
        self.paid = Order.objects.create(
            user_id=self.uid, order_id="SS-1", total=1000, payment_status="paid",
            status="delivered", payload={"items": [], "checkoutData": checkout},
            courier_note="курьер Пётр")
        self.unpaid = Order.objects.create(
            user_id=self.uid, order_id="SS-2", total=500, payment_status="pending",
            payload={"items": [], "checkoutData": checkout})
        with connection.cursor() as cur:
            for _label, table, cols in userdata.RAW_TABLES:
                if table == "territory_events":
                    cur.execute("INSERT INTO territory_events (victim_owner, attacker) "
                                "VALUES (%s, 'someone')", [self.uid])
                elif table == "processed_captures":
                    cur.execute("INSERT INTO processed_captures (capture_id, owner_id) "
                                "VALUES ('c1', %s)", [self.uid])
                elif table == "recent_captures":
                    cur.execute("INSERT INTO recent_captures (owner_id) VALUES (%s)", [self.uid])
                elif table == "footprints":
                    cur.execute("INSERT INTO footprints (owner_id) VALUES (%s)", [self.uid])

    def _left(self):
        """Где ещё остался uid человека."""
        left = {}
        for label, model_label, fields, _p in userdata.MODELS:
            model = userdata._model(model_label)
            if model is None:
                continue
            n = model.objects.filter(userdata._q(fields, self.uid)).count()
            if n:
                left[label] = n
        with connection.cursor() as cur:
            for label, table, cols in userdata.RAW_TABLES:
                where = " OR ".join(f"{c}=%s" for c in cols)
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", [self.uid] * len(cols))
                n = cur.fetchone()[0]
                if n:
                    left[label] = n
        return left

    def test_export_lists_every_registry_section(self):
        r = self.client.get("/v1/account/export", **self.auth)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for label, model_label, _f, _p in userdata.MODELS:
            if userdata._model(model_label) is None or label == "loyaltyTransactions":
                continue
            self.assertIn(label, d)
        self.assertTrue(d["runs"])
        self.assertTrue(d["friendships"])
        self.assertTrue(d["loyalty"]["transactions"])
        for _label, _t, _c in userdata.RAW_TABLES:
            self.assertIn(_label, d)

    def test_delete_leaves_no_trace_but_keeps_financial_record(self):
        self.assertTrue(self._left())
        r = self.client.post("/v1/account/delete", data=json.dumps({"confirm": True}),
                             content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._left(), {})
        self.assertFalse(Account.objects.filter(id=self.uid).exists())

        from loyalty.models import LoyaltyTransaction
        from orders.models import Order

        tomb = userdata.tombstone(self.uid)
        paid = Order.objects.get(pk=self.paid.pk)  # оплаченный заказ сохранён…
        self.assertEqual(paid.user_id, tomb)
        self.assertEqual(paid.courier_note, "")
        co = paid.payload["checkoutData"]
        for key in ("name", "phone", "email", "street", "house"):
            self.assertEqual(co[key], "")  # …но без персональных данных
        self.assertEqual(co["deliveryType"], "courier")
        self.assertFalse(Order.objects.filter(pk=self.unpaid.pk).exists())
        self.assertTrue(LoyaltyTransaction.objects.filter(user_id=tomb).exists())

    def test_order_in_progress_blocks_deletion(self):
        from orders.models import Order

        Order.objects.create(user_id=self.uid, order_id="SS-3", total=900,
                             payment_status="paid", status="pending", payload={"items": []})
        r = self.client.post("/v1/account/delete", data=json.dumps({"confirm": True}),
                             content_type="application/json", **self.auth)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(Account.objects.filter(id=self.uid).exists())

    def test_failure_midway_rolls_everything_back(self):
        from unittest import mock

        from runs.models import Run

        runs_before = Run.objects.filter(user_id=self.uid).count()
        with mock.patch.object(Account, "delete", side_effect=RuntimeError("сбой")):
            with self.assertRaises(RuntimeError):
                self.client.post("/v1/account/delete", data=json.dumps({"confirm": True}),
                                 content_type="application/json", **self.auth)
        self.assertEqual(Run.objects.filter(user_id=self.uid).count(), runs_before)
        self.assertTrue(Account.objects.filter(id=self.uid).exists())
