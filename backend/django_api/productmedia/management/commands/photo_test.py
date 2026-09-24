"""Живой прогон ОДНОГО товара через фотопайплайн — проверить релей и качество ИИ.

По умолчанию режим ПРЕДПРОСМОТРА (--apply НЕ задан): гоняем исходник через GPT, кладём
мастер и webp на задание в S3 и печатаем их ссылки — витрину НЕ трогаем. Посмотрели глазами
на результат → если хорошо, повторяем с --apply, и снимок уходит в галерею витрины.

Примеры (в Cloud Shell на проде):
  # предпросмотр по текущему фото товара (ничего не выкладываем):
  python manage.py photo_test --article ART-123 --from-product
  # предпросмотр по внешней ссылке на исходник:
  python manage.py photo_test --article ART-123 --source-url https://.../raw.jpg
  # выложить результат в галерею витрины (модель+цвет):
  python manage.py photo_test --article ART-123 --from-product --apply
"""
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product
from productmedia import providers, service
from productmedia.matching import _norm
from productmedia.models import PhotoBatch, PhotoJob

MAX_SOURCE_BYTES = 20 * 1024 * 1024


class Command(BaseCommand):
    help = "Прогнать один товар через фотопайплайн (по умолчанию — предпросмотр без привязки)."

    def add_arguments(self, parser):
        parser.add_argument("--article", required=True, help="Артикул товара")
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument("--from-product", action="store_true",
                         help="Исходник = текущее фото товара")
        src.add_argument("--source-url", help="Исходник по внешней ссылке")
        parser.add_argument("--track", choices=["catalog", "model"], default="catalog")
        parser.add_argument("--attach", choices=["main", "gallery"], default="main",
                            help="Куда при --apply: обложка (main) или в галерею")
        parser.add_argument("--apply", action="store_true",
                            help="Выложить результат в галерею витрины (иначе только предпросмотр)")

    def handle(self, *args, **o):
        # 1) товар по артикулу
        product = next((p for p in Product.objects.filter(article__iexact=o["article"].strip())), None)
        if product is None:
            # запасной поиск по нормализованному артикулу (пробелы/регистр)
            want = _norm(o["article"])
            product = next((p for p in Product.objects.exclude(article="")
                            if _norm(p.article) == want), None)
        if product is None:
            raise CommandError("товар с артикулом %r не найден" % o["article"])

        # 2) исходник
        if o["from_product"]:
            if not product.image:
                raise CommandError("у товара нет загруженного фото (--from-product не подходит)")
            with product.image.open("rb") as f:
                source = f.read()
            src_desc = "текущее фото товара"
        else:
            source = self._download(o["source_url"])
            src_desc = o["source_url"]

        # 3) состояние провайдера — чтобы сразу видеть, включён ли релей
        self.stdout.write("Провайдер: OPENAI_API_KEY=%s, base_url=%s"
                          % ("есть" if providers.openai_enabled() else "НЕТ", providers.base_url()))
        self.stdout.write("Товар: %s (%s) | модель=%s | цвета=%s | исходник=%s"
                          % (product.id, product.article, product.shop_model_key or "—",
                             product.colors or [], src_desc))

        # 4) один прогон
        batch = PhotoBatch.objects.create(track=o["track"], note="photo_test")
        job = service.intake(batch, [{
            "article": product.article, "content": source,
            "filename": "source.bin", "attach_as": o["attach"],
        }])[0]
        service.run_job(job, attach=o["apply"])
        job.refresh_from_db()

        # 5) отчёт
        self.stdout.write("Статус задания: %s" % job.get_status_display())
        if job.error:
            self.stdout.write(self.style.ERROR("Ошибка: %s" % job.error))
        if job.master:
            self.stdout.write("Мастер (ИИ):   %s" % _url(job.master))
        if job.webp:
            self.stdout.write("Витринный webp: %s" % _url(job.webp))

        if job.status != PhotoJob.STATUS_DONE:
            raise CommandError("прогон не удался (см. ошибку выше)")

        if o["apply"]:
            self.stdout.write(self.style.SUCCESS(
                "Готово: снимок выложен в галерею витрины (модель+цвет). "
                "Открой карточку на сайте/в приложении. Если плохо — удали в админке «Фото товаров»."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Предпросмотр готов: открой ссылки выше и посмотри результат. "
                "Если нравится — повтори с --apply, снимок уйдёт на витрину."))

    def _download(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "mata-photo-test"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — ссылку даёт владелец
            data = r.read(MAX_SOURCE_BYTES + 1)
        if not data:
            raise CommandError("по ссылке пусто")
        if len(data) > MAX_SOURCE_BYTES:
            raise CommandError("исходник больше %d МБ" % (MAX_SOURCE_BYTES // 1024 // 1024))
        return data


def _url(field):
    try:
        return field.url
    except Exception:                       # noqa: BLE001 — при локальном хранилище без URL
        return field.name
