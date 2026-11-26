"""Контент 26.11.2026 (замечания владельца): демо-баннеры сняты с публикации,
описания товаров вычитаны (канцелярит, кальки, опечатки — «ежедневных перемещений»
и подобное). Сами правки — catalog/content_fixes/copy_2026_11_26.json."""
from django.db import migrations


def forward(apps, schema_editor):
    from catalog.content_fixes import apply_copy_fixes, load_pairs, unpublish_demo_banners

    unpublish_demo_banners(apps.get_model("catalog", "Banner"))
    apply_copy_fixes(apps.get_model("catalog", "Product"), load_pairs("copy_2026_11_26.json"))


class Migration(migrations.Migration):
    dependencies = [("catalog", "0029_favorite")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
