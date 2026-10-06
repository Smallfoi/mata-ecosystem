# -*- coding: utf-8 -*-
"""Оценка достоверности записи с часов (D-108).

Смысл проверок — не «алгоритм работает», а «он различает две конкретные вещи»:
запись настоящих часов (паспорт устройства, живой пульс и каденс, дрожащий GPS)
и нарисованный на компьютере трек (ровные шаги по прямой, пульса нет, устройства
нет). Поэтому тесты собирают оба файла и смотрят на вывод целиком.
"""
import math
import random

from django.test import SimpleTestCase

from workouts import trust


def _drawn_track(n=120, step_m=10.0):
    """Нарисованный маршрут: ровные шаги по прямой, без датчиков."""
    points = []
    for i in range(n):
        points.append({
            "lat": 62.0 + i * (step_m / 111_320.0),
            "lon": 129.7,
            "at": i,
        })
    return {"points": points, "device": {}, "sport": "running"}


def _recorded_track(n=120, seed=7):
    """Запись часов: шаги разной длины, трек виляет, пульс и каденс живут."""
    rnd = random.Random(seed)
    points, lat, lon = [], 62.0, 129.7
    hr, cadence = 140, 168
    for i in range(n):
        step = 3.2 + rnd.uniform(-1.4, 1.4)                 # темп плавает
        lat += step / 111_320.0
        lon += rnd.uniform(-2.5, 2.5) / (111_320.0 * math.cos(math.radians(lat)))
        hr = max(110, min(180, hr + rnd.randint(-3, 3)))     # пульс дрейфует
        cadence = max(150, min(185, cadence + rnd.randint(-4, 4)))
        points.append({
            "lat": lat, "lon": lon, "at": i,
            "hr": hr, "cadence": cadence,
            "speed": 3.2 + rnd.uniform(-0.5, 0.5),
        })
    return {
        "points": points,
        "device": {"manufacturer": "suunto", "product": "Race S", "serial": "123456"},
        "sport": "running",
    }


class TrustScoreTests(SimpleTestCase):
    def test_real_watch_recording_is_trusted(self):
        verdict = trust.score(_recorded_track())
        self.assertEqual(verdict["level"], trust.HIGH, verdict["reasons"])

    def test_drawn_route_is_not_trusted(self):
        verdict = trust.score(_drawn_track())
        self.assertEqual(verdict["level"], trust.LOW)
        self.assertTrue(verdict["reasons"], "отказ без объяснения бесполезен человеку")

    def test_track_without_sensors_lands_in_the_middle(self):
        """Паспорт устройства есть, живой GPS есть, а пульса и каденса нет.

        Так выглядит запись старых часов без нагрудного датчика: километры
        засчитываем, захват придерживаем.
        """
        data = _recorded_track()
        for p in data["points"]:
            p.pop("hr", None)
            p.pop("cadence", None)
        self.assertEqual(trust.score(data)["level"], trust.MEDIUM)

    def test_reasons_name_what_is_missing(self):
        verdict = trust.score(_drawn_track())
        joined = " ".join(verdict["reasons"])
        self.assertIn("паспорт", joined)
        self.assertIn("пульс", joined)

    def test_short_track_is_not_enough_to_trust(self):
        """Пять точек — не повод верить: по ним ничего не видно."""
        data = _recorded_track(n=5)
        self.assertNotEqual(trust.score(data)["level"], trust.HIGH)

    def test_no_track_at_all_is_middle_not_refusal(self):
        """Сводка без трека — не обман, а отсутствие данных."""
        self.assertEqual(trust.unknown()["level"], trust.MEDIUM)
        self.assertEqual(trust.score({"points": [], "device": {}})["level"], trust.LOW)

    def test_constant_heart_rate_does_not_earn_points(self):
        """Ровный как по линейке пульс — признак рисунка, а не бега."""
        data = _recorded_track()
        for p in data["points"]:
            p["hr"] = 150
        with_constant = trust.score(data)["score"]
        self.assertLess(with_constant, trust.score(_recorded_track())["score"])
