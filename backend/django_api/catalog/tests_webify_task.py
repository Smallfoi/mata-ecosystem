"""Фоновые видео сайта сжимает beat (17.11.2026): разовую команду 25.09 не запустили,
и исходники по 100 МБ грузились на каждом заходе."""
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from catalog import tasks


class WebifyTaskTests(TestCase):
    def tearDown(self):
        cache.delete(tasks._LOCK)

    def test_runs_the_command_with_apply_and_releases_the_lock(self):
        with patch.object(tasks, "call_command") as cmd:
            tasks.webify_site_videos()
        cmd.assert_called_once_with("webify_site_videos", apply=True)
        self.assertIsNone(cache.get(tasks._LOCK))

    def test_a_second_run_waits_for_the_first(self):
        cache.add(tasks._LOCK, 1, 60)
        with patch.object(tasks, "call_command") as cmd:
            tasks.webify_site_videos()
        cmd.assert_not_called()

    def test_lock_is_released_even_if_the_command_fails(self):
        with patch.object(tasks, "call_command", side_effect=RuntimeError("ffmpeg")):
            with self.assertRaises(RuntimeError):
                tasks.webify_site_videos()
        self.assertIsNone(cache.get(tasks._LOCK))

    def test_beat_runs_it(self):
        tasks_in_beat = {e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn("catalog.webify_site_videos", tasks_in_beat)
