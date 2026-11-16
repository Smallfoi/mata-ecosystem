"""Перевести устаревшие сохранённые промты на встроенный v3 (просьба владельца 16.11.2026).

Версия промта, сохранённая на странице «Промты», перекрывает встроенный текст целиком.
С сентября там лежала сохранённая версия — и все улучшения встроенного промта в коде
до генерации на проде не доходили: владелец видел на вкладке старый текст и правильно
спросил, где новый.

Для каждого трека: если действующая версия есть и отличается от встроенного v3 —
создаём новую версию с текстом v3. Старая остаётся в истории, её можно вернуть одной
кнопкой. Если сохранённой версии нет — ничего не делаем: встроенный и так действует
и будет обновляться вместе с кодом.

Текст берём из живого модуля намеренно: смысл миграции — «встать на текущий встроенный».
На чистой базе версий нет, и миграция ничего не пишет.
"""
from django.db import migrations

COMMENT = ("встроенный v3: вещь по карточке и категории 1С, "
           "постановка кадра для одежды / обуви / аксессуаров")


def forward(apps, schema_editor):
    from productmedia import processing

    PhotoPrompt = apps.get_model("productmedia", "PhotoPrompt")
    for track, (builtin, _size, _fidelity) in processing.TRACKS.items():
        active = (PhotoPrompt.objects.filter(track=track)
                  .order_by("-created_at", "-id").first())
        if active is None or active.text.strip() == builtin.strip():
            continue
        PhotoPrompt.objects.create(track=track, text=builtin, comment=COMMENT)


class Migration(migrations.Migration):

    dependencies = [
        ("productmedia", "0007_alter_photojob_status"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
