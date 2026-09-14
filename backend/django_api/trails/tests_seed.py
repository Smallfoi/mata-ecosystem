"""Сид троп: команда заводит реальные маршруты Якутска (D-74)."""
from django.core.management import call_command
from django.test import TestCase

from trails.models import Trail


class SeedTrailsTests(TestCase):
    def test_seed_loads_trails(self):
        call_command("seed_trails")
        self.assertGreaterEqual(Trail.objects.count(), 3)
        # у каждой тропы есть линия и рамка
        for t in Trail.objects.all():
            self.assertGreaterEqual(len(t.points), 2)
            self.assertLess(t.min_lat, t.max_lat)
            self.assertGreater(t.length_m, 0)

    def test_seed_is_idempotent(self):
        call_command("seed_trails")
        before = Trail.objects.count()
        call_command("seed_trails")
        self.assertEqual(Trail.objects.count(), before)
