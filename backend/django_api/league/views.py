"""API лиги: зачёты и профиль бегуна.

Контракт (ECOSYSTEM_API.md):
    GET  /v1/league/boards?board=<...>&period=<week|month|q90>
    GET  /v1/runner/profile
    POST /v1/runner/profile
"""
from datetime import datetime
from datetime import timezone as dt_tz

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.security import user_id_from_request
from league import divisions as divisions_svc
from league import seasons as seasons_svc
from league import services
from league.models import RunnerProfile

MIN_BIRTH_YEAR = 1900
MAX_GOAL_KM = 500     # разумный потолок недельной цели: выше — опечатка, а не цель


@api_view(["GET"])
def boards(request):
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    board = request.query_params.get("board", "absolute")
    if board not in services.BOARDS:
        board = "absolute"
    period = request.query_params.get("period", "week")
    if period not in services.PERIODS:
        period = "week"

    if board == "personal":
        data = services.board_personal(me, period)
    else:
        data = services.BOARD_FUNCS[board](me, period)

    return Response({"board": board, "period": period, **data})


@api_view(["GET", "POST"])
def profile(request):
    me = user_id_from_request(request)
    if not me:
        return Response({"detail": "Нет токена"}, status=401)

    obj, _ = RunnerProfile.objects.get_or_create(user_id=me)

    if request.method == "GET":
        return Response({**obj.to_json(), "group": _group_of(obj)})

    data = request.data if isinstance(request.data, dict) else {}

    # Каждое поле необязательно, но если пришло — проверяем. Пустая строка и None
    # означают «стереть»: человек вправе передумать и убрать возраст из профиля.
    if "birthYear" in data:
        year = data.get("birthYear")
        if year in (None, ""):
            obj.birth_year = None
        else:
            try:
                year = int(year)
            except (TypeError, ValueError):
                return Response({"detail": "Год рождения — число"}, status=400)
            this_year = datetime.now(dt_tz.utc).year
            if year < MIN_BIRTH_YEAR or year > this_year:
                return Response({"detail": "Год рождения вне разумных границ"}, status=400)
            obj.birth_year = year

    if "gender" in data:
        gender = (data.get("gender") or "").strip().lower()
        if gender not in ("m", "f", ""):
            return Response({"detail": "Пол: m, f или пусто"}, status=400)
        obj.gender = gender

    if "level" in data:
        level = (data.get("level") or "").strip().lower()
        if level not in ("novice", "amateur", "advanced", ""):
            return Response({"detail": "Уровень: novice, amateur, advanced или пусто"}, status=400)
        obj.level = level

    if "weeklyGoalKm" in data:
        goal = data.get("weeklyGoalKm")
        if goal in (None, ""):
            obj.weekly_goal_km = None
        else:
            try:
                goal = float(goal)
            except (TypeError, ValueError):
                return Response({"detail": "Цель — число километров"}, status=400)
            if goal <= 0 or goal > MAX_GOAL_KM:
                return Response({"detail": "Цель вне разумных границ"}, status=400)
            obj.weekly_goal_km = goal

    if "focus" in data:
        focus = (data.get("focus") or "").strip().lower()
        if focus not in ("health", "compete", "social", "calm", "skip", ""):
            return Response({"detail": "Неизвестная цель"}, status=400)
        obj.focus = focus

    if "trailsEnabled" in data:
        obj.trails_enabled = bool(data.get("trailsEnabled"))

    if "trackBackup" in data:
        obj.track_backup = bool(data.get("trackBackup"))

    obj.updated_at = timezone.now()
    obj.save()
    return Response({**obj.to_json(), "group": _group_of(obj)})


def _group_of(obj):
    """Группа сравнения — то, что человек увидит как «своя лига»."""
    age = services.age_group(obj.birth_year)
    if not age or not obj.gender:
        return None
    return {
        "age": age,
        "gender": obj.gender,
        "label": services.group_label(age, obj.gender),
    }


@api_view(["GET"])
def division(request):
    """Дивизион недели (Квартал 2.0, Ф0/Ф5): группа до 30 бегунов твоего уровня.

    Ленивое назначение и ленивое закрытие прошлой недели — см. league.divisions.
    """
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    return Response(divisions_svc.division_payload(uid))


@api_view(["GET"])
def season_latest(request):
    """Итог прошлого сезона (месяца) — для церемонии в приложении."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    return Response(seasons_svc.season_payload(uid))
