# -*- coding: utf-8 -*-
"""Проставить честные заголовки уже лежащим в S3 публичным медиа.

1. Content-Type WebP/AVIF: до 18.11.2026 сервер не знал тип `.webp`, и хранилище
   записывало фото как `application/octet-stream`.
2. Cache-Control (21.11.2026): до этого публичные фото лежали без него, и браузер
   качал их заново при каждом визите. Новые файлы получают его из common/media.py.

Команда копирует объект сам в себя с новыми метаданными (содержимое не меняется),
доступ оставляет публичным.

    python manage.py fix_media_content_types            # показать
    python manage.py fix_media_content_types --apply    # исправить
"""
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from common.media import MEDIA_CACHE_CONTROL

TYPES = {".webp": "image/webp", ".avif": "image/avif"}
# Публичные медиа, которым нужен кэш. Тип у остальных расширений S3 знает сам.
MEDIA_EXT = (".webp", ".avif", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".webm")
# Только публичные папки витрины. Приватные файлы (photopipeline/, returns/) лежат в
# том же бакете — копирование с ACL public-read открыло бы их всем.
PREFIXES = ("uploads/photos/", "uploads/site/", "uploads/banners/",
            "uploads/categories/", "uploads/products/")
ALL_USERS = "http://acs.amazonaws.com/groups/global/AllUsers"


def _is_public(client, bucket, key) -> bool:
    acl = client.get_object_acl(Bucket=bucket, Key=key)
    return any(g.get("Grantee", {}).get("URI") == ALL_USERS and g.get("Permission") == "READ"
               for g in acl.get("Grants", []))


class Command(BaseCommand):
    help = "Исправить Content-Type WebP/AVIF и проставить Cache-Control публичным медиа в S3"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        bucket = getattr(default_storage, "bucket", None)
        if bucket is None:
            self.stdout.write("Хранилище не S3 — исправлять нечего.")
            return
        client = bucket.meta.client
        fixed = wrong = 0
        objects = (o for prefix in PREFIXES for o in bucket.objects.filter(Prefix=prefix))
        for obj in objects:
            key = obj.key.lower()
            if not key.endswith(MEDIA_EXT):
                continue
            head = client.head_object(Bucket=bucket.name, Key=obj.key)
            current = head.get("ContentType") or ""
            want = next((t for ext, t in TYPES.items() if key.endswith(ext)), current)
            if current == want and head.get("CacheControl") == MEDIA_CACHE_CONTROL:
                continue
            if not _is_public(client, bucket.name, obj.key):
                self.stdout.write(f"  {obj.key}: не публичный — пропуск")
                continue
            wrong += 1
            if not opts["apply"]:
                continue
            client.copy_object(
                Bucket=bucket.name, Key=obj.key,
                CopySource={"Bucket": bucket.name, "Key": obj.key},
                MetadataDirective="REPLACE", ContentType=want, ACL="public-read",
                Metadata=head.get("Metadata") or {}, CacheControl=MEDIA_CACHE_CONTROL,
            )
            fixed += 1
        if opts["apply"]:
            self.stdout.write(f"Исправлено: {fixed}.")
        else:
            self.stdout.write(f"С неверными заголовками: {wrong}. Повторите с --apply.")
