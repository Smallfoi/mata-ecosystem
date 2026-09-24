"""Каталог Store (D-13). Публичные read-эндпоинты — токен не нужен.
Контракт совпадает с ApiProductRepository в SportStore."""
import secrets

from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view, throttle_classes

from common.throttling import PUBLIC_READ
from rest_framework.response import Response

from accounts.models import Account
from common.uploads import image_extension
from common.security import user_id_from_request
from orders.models import Order

from .models import Banner, Category, Product, Review, SiteContent

_TRUE = {"1", "true", "True", "yes"}


def _is_preview(request) -> bool:
    """preview=1 → отдаём и черновики (для админ-превью); иначе только опубликованное."""
    return request.query_params.get("preview") in _TRUE


def _visible_products(request):
    """На витрине — только опубликованное владельцем И не снятое с продажи в 1С.
    Это два независимых решения: владелец прячет товар, 1С снимает с продажи."""
    qs = Product.objects.all()
    if not _is_preview(request):
        qs = qs.filter(is_published=True, is_active_1c=True)
    return qs


def _platform_order(request):
    """Порядок витрины по площадке (мерчендайзинг per-channel). platform=site|app →
    свой порядок (sort_site/sort_app); без параметра — общий sort (обратная совместимость)."""
    platform = (request.query_params.get("platform") or "").strip().lower()
    field = {"site": "sort_site", "app": "sort_app"}.get(platform)
    return (field, "sort", "id") if field else ("sort", "id")


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def categories(request):
    return Response([c.to_json() for c in Category.objects.all()])


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def products(request):
    qs = _visible_products(request)
    cat = request.query_params.get("category")
    if cat and cat != "all":
        qs = qs.filter(category_id=cat)
    if request.query_params.get("featured") in _TRUE:
        qs = qs.filter(is_featured=True)
    if request.query_params.get("new") in _TRUE:
        qs = qs.filter(is_new=True)
    qs = qs.order_by(*_platform_order(request))
    return Response([p.to_json() for p in qs])


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def product_search(request):
    q = (request.query_params.get("q") or "").strip()
    qs = _visible_products(request)
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(description__icontains=q) | Q(brand__icontains=q)
        )
    return Response([p.to_json() for p in qs])


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def product_price_range(request):
    vals = list(Product.objects.values_list("price", flat=True))
    if not vals:
        return Response({"min": 0, "max": 0})
    return Response({"min": min(vals), "max": max(vals)})


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def product_detail(request, pid):
    p = Product.objects.filter(id=pid).first()
    if not p or (not p.is_published and not _is_preview(request)):
        return Response({"detail": "Товар не найден"}, status=404)
    return Response(p.to_json())


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def brands(request):
    return Response(sorted(set(Product.objects.values_list("brand", flat=True))))


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def sizes(request):
    order = ["XS", "S", "M", "L", "XL", "XXL", "39", "40", "41", "42", "43", "44", "45"]
    found = set()
    for arr in Product.objects.values_list("sizes", flat=True):
        for s in (arr or []):
            if s != "Один размер":
                found.add(s)
    return Response(
        sorted(found, key=lambda x: (order.index(x) if x in order else 999, x))
    )


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def banners(request):
    qs = Banner.objects.all()
    if not _is_preview(request):
        qs = qs.filter(is_published=True)
    qs = qs.order_by(*_platform_order(request))
    return Response([b.to_json() for b in qs])


@api_view(["GET"])
@throttle_classes(PUBLIC_READ)
def site_content(request):
    """Редактируемый контент сайта (тексты/фото шапки, hero, секций) для мини-CMS.
    Сайт подставляет по data-edit / data-edit-img. Публичный (как каталог)."""
    return Response({c.key: c.to_json() for c in SiteContent.objects.all()})


# ── Отзывы на товары ────────────────────────────────────────────────────────

def _recompute_rating(product_ids):
    """Пересчитать рейтинг модели по её отзывам.

    Отзыв покупатель пишет на МОДЕЛЬ, а купил один размер (D-94): считаем по
    всем позициям модели и одно и то же значение пишем каждой из них — чтобы
    рейтинг был один и на карточке модели, и на отдельной позиции.
    """
    ids = [product_ids] if isinstance(product_ids, str) else list(product_ids)
    # Скрытые модерацией отзывы не влияют на рейтинг.
    agg = Review.objects.filter(product_id__in=ids, hidden=False).aggregate(
        a=Avg("rating"), c=Count("id")
    )
    Product.objects.filter(id__in=ids).update(
        rating=round(agg["a"] or 0, 1), review_count=agg["c"] or 0
    )


def _has_purchased(uid, product_id):
    return bool(_purchased_position(uid, [product_id]))


def _purchased_position(uid, product_ids):
    """Какую из позиций модели человек купил (или None). Отзыв пишем именно на
    неё: так остаётся видно, какой размер человек носил."""
    wanted = set(product_ids)
    for o in Order.objects.filter(user_id=uid).only("payload"):
        for it in (o.payload or {}).get("items", []):
            if isinstance(it, dict) and str(it.get("productId") or "") in wanted:
                return str(it["productId"])
    return None


def _review_name(uid):
    a = Account.objects.filter(id=uid).only("name").first()
    return a.name if (a and a.name) else "Покупатель"


def _review_json(r, uid):
    return {
        "id": r.id,
        "userId": r.user_id,
        "name": _review_name(r.user_id),
        "rating": r.rating,
        "text": r.text,
        "photos": r.photos or [],
        "createdAt": r.created_at.isoformat(),
        "mine": r.user_id == uid,
    }


@api_view(["GET", "POST"])
@throttle_classes(PUBLIC_READ)
def product_reviews(request, pid):
    """GET — список отзывов товара (+ можно ли оставить). POST — оставить/обновить
    свой отзыв (только купившие товар). Рейтинг товара пересчитывается.

    `pid` — либо позиция склада, либо ключ модели: витрина показывает модель, а
    склад ведёт размеры отдельными карточками (D-94). Отзывы у модели общие —
    иначе отзыв о кроссовках виден только тем, кто смотрит ровно 42-й размер.
    """
    from .models_api import siblings_of

    items = siblings_of(pid)
    if not items:
        return Response({"detail": "Товар не найден"}, status=404)
    ids = [p.id for p in items]
    product = items[0]
    uid = user_id_from_request(request)
    if request.method == "GET":
        reviews = [
            _review_json(r, uid)
            for r in Review.objects.filter(product_id__in=ids, hidden=False)
        ]
        return Response(
            {
                "rating": product.rating,
                "reviewCount": product.review_count,
                "reviews": reviews,
                "canReview": bool(uid and _purchased_position(uid, ids)),
                "hasMine": any(r["mine"] for r in reviews) if uid else False,
            }
        )
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    bought = _purchased_position(uid, ids)
    if not bought:
        return Response({"detail": "Отзыв доступен после покупки товара"}, status=403)
    d = request.data
    try:
        rating = int(d.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        return Response({"detail": "Оценка должна быть от 1 до 5"}, status=400)
    text = (d.get("text") or "").strip()[:2000]
    # Фото отзыва: до 5 URL (загружаются через POST /v1/reviews/photo).
    photos = d.get("photos")
    if not isinstance(photos, list):
        photos = []
    photos = [str(p).strip() for p in photos if isinstance(p, str) and p.strip()][:5]
    # Отзыв храним на купленной позиции, но ищем по всей модели: второй отзыв
    # на те же кроссовки в другом размере — это всё тот же один отзыв.
    obj = Review.objects.filter(product_id__in=ids, user_id=uid).first()
    if obj:
        obj.rating = rating
        obj.text = text
        obj.photos = photos
        obj.created_at = timezone.now()
        obj.save()
    else:
        obj = Review.objects.create(
            id=f"rev_{secrets.token_hex(8)}",
            product_id=bought,
            user_id=uid,
            rating=rating,
            text=text,
            photos=photos,
        )
    _recompute_rating(ids)
    product.refresh_from_db()
    return Response(
        {
            "rating": product.rating,
            "reviewCount": product.review_count,
            "review": _review_json(obj, uid),
        }
    )


@api_view(["POST"])
def review_photo(request):
    """Загрузка фото к отзыву (multipart `image`) → URL в media. Авторизованные;
    право оставить отзыв проверяется при сохранении (купившие товар)."""
    uid = user_id_from_request(request)
    if not uid:
        return Response({"detail": "Нет токена"}, status=401)
    f = request.FILES.get("image")
    # Тип определяем по СОДЕРЖИМОМУ: имя файла и Content-Type присылает клиент (D-37).
    ext, upload_error = image_extension(f)
    if upload_error:
        return Response({"detail": upload_error}, status=400)
    from django.core.files.storage import default_storage

    saved = default_storage.save(
        f"uploads/reviews/{uid}_{secrets.token_hex(6)}.{ext}", f
    )
    return Response({"url": default_storage.url(saved)})  # локально /media/…, в проде S3/CDN (D-31)
