"""WebP в S3 с честным Content-Type (18.11.2026): новые — через mimetypes, старые —
командой; приватные файлы команда не трогает."""
import mimetypes
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase

import common.media  # noqa: F401 — регистрирует image/webp

PUBLIC = {"Grants": [{"Grantee": {"URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
                      "Permission": "READ"}]}


def _bucket(objects):
    client = MagicMock()
    client.head_object.side_effect = lambda Bucket, Key: dict(
        {"ContentType": objects[Key][0]},
        **({"CacheControl": objects[Key][2]} if len(objects[Key]) > 2 else {}))
    client.get_object_acl.side_effect = lambda Bucket, Key: objects[Key][1]
    bucket = MagicMock()
    bucket.name = "b"
    bucket.meta.client = client
    bucket.objects.filter.side_effect = lambda Prefix: [
        SimpleNamespace(key=k) for k in objects if k.startswith(Prefix)]
    return bucket, client


class ContentTypeTests(SimpleTestCase):
    def test_webp_type_is_known(self):
        self.assertEqual(mimetypes.guess_type("x.webp")[0], "image/webp")

    def test_only_public_wrong_webp_is_fixed(self):
        from common.media import MEDIA_CACHE_CONTROL

        bucket, client = _bucket({
            "uploads/photos/a.webp": ("application/octet-stream", PUBLIC, MEDIA_CACHE_CONTROL),
            "uploads/photos/b.webp": ("image/webp", PUBLIC, MEDIA_CACHE_CONTROL),
            "uploads/site/c.webp": ("application/octet-stream", {"Grants": []}),
            "uploads/site/d.jpg": ("image/jpeg", PUBLIC, MEDIA_CACHE_CONTROL),
            "photopipeline/webp/e.webp": ("application/octet-stream", {"Grants": []}),
        })
        with patch("catalog.management.commands.fix_media_content_types.default_storage",
                   SimpleNamespace(bucket=bucket)):
            out = StringIO()
            call_command("fix_media_content_types", apply=True, stdout=out)
        keys = [c.kwargs["Key"] for c in client.copy_object.call_args_list]
        self.assertEqual(keys, ["uploads/photos/a.webp"])
        call = client.copy_object.call_args.kwargs
        self.assertEqual(call["ContentType"], "image/webp")
        self.assertEqual(call["MetadataDirective"], "REPLACE")
        self.assertEqual(call["CacheControl"], MEDIA_CACHE_CONTROL)
        self.assertIn("Исправлено: 1", out.getvalue())

    def test_public_media_without_cache_gets_it_and_keeps_its_type(self):
        from common.media import MEDIA_CACHE_CONTROL

        bucket, client = _bucket({
            "uploads/site/hero.webp": ("image/webp", PUBLIC),
            "uploads/banners/b.jpg": ("image/jpeg", PUBLIC),
            "uploads/site/notes.txt": ("text/plain", PUBLIC),
            "uploads/site/secret.jpg": ("image/jpeg", {"Grants": []}),
        })
        with patch("catalog.management.commands.fix_media_content_types.default_storage",
                   SimpleNamespace(bucket=bucket)):
            call_command("fix_media_content_types", apply=True, stdout=StringIO())
        calls = {c.kwargs["Key"]: c.kwargs for c in client.copy_object.call_args_list}
        self.assertEqual(set(calls), {"uploads/site/hero.webp", "uploads/banners/b.jpg"})
        self.assertEqual(calls["uploads/banners/b.jpg"]["ContentType"], "image/jpeg")
        self.assertTrue(all(c["CacheControl"] == MEDIA_CACHE_CONTROL for c in calls.values()))

    def test_new_uploads_get_cache_header_private_do_not(self):
        from common.media import MEDIA_CACHE_CONTROL, media_storages

        env = {"MEDIA_S3_BUCKET": "b", "MEDIA_S3_ACCESS_KEY": "a", "MEDIA_S3_SECRET_KEY": "s"}
        st = media_storages(env)
        self.assertEqual(st["default"]["OPTIONS"]["object_parameters"],
                         {"CacheControl": MEDIA_CACHE_CONTROL})
        self.assertEqual(st["private"]["OPTIONS"]["object_parameters"], {})

    def test_dry_run_copies_nothing(self):
        bucket, client = _bucket({"uploads/site/a.webp": ("application/octet-stream", PUBLIC)})
        with patch("catalog.management.commands.fix_media_content_types.default_storage",
                   SimpleNamespace(bucket=bucket)):
            call_command("fix_media_content_types", stdout=StringIO())
        client.copy_object.assert_not_called()
