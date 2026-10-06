# -*- coding: utf-8 -*-
"""Разбор FIT-файла тренировки: трек, датчики, паспорт устройства.

FIT — двоичный формат, в котором часы пишут тренировку: подряд идут записи
(record) с координатами, пульсом, каденсом и временем, а в начале — служебные
сообщения о самом устройстве (производитель, модель, серийный номер, прошивка).

Нам отсюда нужно три вещи:
- **трек** — для захвата кварталов и сверки с тропами;
- **датчики** — пульс и каденс: по ним видно, что бежал человек, а не рисовала
  программа;
- **паспорт устройства** — им подписана настоящая запись часов.

Всё это уходит в оценку достоверности (D-108): тренировку с часов мы засчитываем
полностью, но ровно настолько, насколько верим, что она настоящая.

Разбором занимается `fitparse` — пересказывать двоичный формат своими руками
незачем. Наше здесь — перевод его записей в простой вид, понятный остальному коду.
"""
import io
import logging

log = logging.getLogger(__name__)

# Координаты в FIT хранятся в «полуокружностях»: целое число, где полный круг —
# это 2³². Отсюда и множитель.
SEMICIRCLE = 180.0 / (2 ** 31)


class FitError(RuntimeError):
    """Файл не разобрался: битый, обрезанный или не FIT вовсе."""


def _point(record) -> dict | None:
    """Одна запись трека → точка. Без координат точка нам не нужна."""
    values = {d.name: d.value for d in record}
    lat, lon = values.get("position_lat"), values.get("position_long")
    if lat is None or lon is None:
        return None
    point = {
        "lat": lat * SEMICIRCLE,
        "lon": lon * SEMICIRCLE,
        "at": values.get("timestamp"),
    }
    for key, name in (("hr", "heart_rate"), ("cadence", "cadence"),
                      ("speed", "speed"), ("altitude", "altitude")):
        value = values.get(name)
        if value is not None:
            point[key] = value
    return point


def parse(data: bytes) -> dict:
    """FIT → {'points': [...], 'device': {...}, 'sport': str}.

    Кидает FitError, если файл не читается: пустая тренировка и битый файл —
    разные вещи, и вызывающий должен их различать.
    """
    if not data:
        raise FitError("пустой файл")
    try:
        from fitparse import FitFile
    except ImportError as e:                      # библиотеки нет в окружении
        raise FitError("нет библиотеки разбора FIT") from e

    try:
        fit = FitFile(io.BytesIO(bytes(data)))
        fit.parse()
    except Exception as e:                        # битый, обрезанный, не FIT
        raise FitError(f"файл не разобрался: {e}") from e

    points = []
    for record in fit.get_messages("record"):
        point = _point(record)
        if point:
            points.append(point)

    device = {}
    for message in fit.get_messages("file_id"):
        values = {d.name: d.value for d in message}
        device.update({
            "manufacturer": str(values.get("manufacturer") or ""),
            "product": str(values.get("product") or values.get("garmin_product") or ""),
            "serial": str(values.get("serial_number") or ""),
            "created_at": values.get("time_created"),
        })
        break
    for message in fit.get_messages("device_info"):
        values = {d.name: d.value for d in message}
        version = values.get("software_version")
        if version is not None:
            device["firmware"] = str(version)
            break

    sport = ""
    for message in fit.get_messages("sport"):
        values = {d.name: d.value for d in message}
        sport = str(values.get("sport") or "")
        break

    return {"points": points, "device": device, "sport": sport}
