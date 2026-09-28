# Территории хранятся в PostGIS-таблице `territories` (geometry MultiPolygon).
# Работаем с ней через raw SQL (ST_Union/ST_Difference/...), без GeoDjango/GDAL.
# Схема создаётся миграцией 0001_initial (RunSQL).

from django.db import models  # noqa: E402
from django.utils import timezone  # noqa: E402


class CaptureAward(models.Model):
    """Баллы за захват и пробежка, к которой он относится (решение 28.09.2026, п.4).

    Территория на карте засчитывается сразу, а БАЛЛЫ за неё — только если у
    бегуна есть принятая (не помеченная) пробежка, к которой захват относится.
    Захват и сводка пробежки приходят раздельно и в любом порядке (на финише оба
    запроса летят одновременно, из офлайн-очереди — когда появится связь),
    поэтому захват без найденной пробежки не отбивается, а ждёт её здесь
    (`pending`); сводка пробежки, придя, доводит начисление ровно один раз
    (дедуп по `capture_id` в истории баллов).
    """

    PENDING = "pending"      # ждёт пробежку (или решения модератора по ней)
    AWARDED = "awarded"      # баллы выплачены (возможно, частично — потолок)
    REJECTED = "rejected"    # пробежка признана нарушением — баллов не будет

    capture_id = models.CharField(primary_key=True, max_length=64, verbose_name="Захват (ID)")
    user_id = models.CharField(max_length=40, db_index=True, verbose_name="Пользователь (ID)")
    points = models.IntegerField(default=0, verbose_name="Баллов за новую землю")
    awarded = models.IntegerField(default=0, verbose_name="Выплачено")
    # runId от клиента (новые сборки) или найденная по времени и цифрам пробежка.
    run_id = models.CharField(max_length=40, blank=True, default="", db_index=True,
                              verbose_name="Пробежка (ID)")
    distance_m = models.FloatField(default=0, verbose_name="Дистанция из захвата, м")
    route_m = models.FloatField(default=0, verbose_name="Длина контура, м")
    elapsed_s = models.IntegerField(default=0, verbose_name="Время из захвата, с")
    status = models.CharField(max_length=10, default=PENDING, db_index=True,
                              verbose_name="Статус")
    note = models.CharField(max_length=200, blank=True, default="", verbose_name="Пометка")
    created_at = models.DateTimeField(default=timezone.now, db_index=True,
                                      verbose_name="Получен")
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name="Решён")

    class Meta:
        db_table = "territory_capture_awards"
        verbose_name = "Баллы за захват"
        verbose_name_plural = "Баллы за захваты"
