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
    client.head_object.side_effect = lambda Bucket, Key: {"ContentType": objects[Key][0]}
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
        bucket, client = _bucket({
            "uploads/photos/a.webp": ("application/octet-stream", PUBLIC),
            "uploads/photos/b.webp": ("image/webp", PUBLIC),
            "uploads/site/c.webp": ("application/octet-stream", {"Grants": []}),
            "uploads/site/d.jpg": ("image/jpeg", PUBLIC),
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
        self.assertNotIn("CacheControl", call)
        self.assertIn("Исправлено: 1", out.getvalue())

    def test_dry_run_copies_nothing(self):
        bucket, client = _bucket({"uploads/site/a.webp": ("application/octet-stream", PUBLIC)})
        with patch("catalog.management.commands.fix_media_content_types.default_storage",
                   SimpleNamespace(bucket=bucket)):
            call_command("fix_media_content_types", stdout=StringIO())
        client.copy_object.assert_not_called()
