from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import require_roles
from models import (
    CollectionEvent,
    CollectionZone,
    RequestStatus,
    User,
    UserRole,
    WasteRequest,
    WasteType,
    ZoneStatus,
)
from schemas import CollectionZoneOut, ZoneComplete
from services.collection_access import visible_zone_condition, zone_has_request
from services.esg import CO2E_FORMULA_RU, calculate_co2_saved
from services.geo import compute_route, compute_route_for_zone
from security import rate_limit

router = APIRouter()


@router.get("/map-requests", dependencies=[Depends(rate_limit("recycler-map-requests", limit=60, window_seconds=60))])
async def map_requests(
    min_kg: float | None = Query(None, ge=0),
    max_kg: float | None = Query(None, ge=0),
    status: RequestStatus | None = None,
    q: str = Query("", max_length=160),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER)),
):
    if min_kg is not None and max_kg is not None and min_kg > max_kg:
        raise HTTPException(422, "Некорректный диапазон массы")
    query = (
        select(WasteRequest, CollectionZone.id)
        .join(CollectionZone, zone_has_request())
        .where(visible_zone_condition(current_user))
    )
    if min_kg is not None:
        query = query.where(WasteRequest.weight_kg >= min_kg)
    if max_kg is not None:
        query = query.where(WasteRequest.weight_kg <= max_kg)
    if status is not None:
        query = query.where(WasteRequest.status == status)
    if needle := q.strip():
        query = query.where(or_(
            WasteRequest.address.icontains(needle, autoescape=True),
            WasteRequest.pickup_note.icontains(needle, autoescape=True),
        ))
    limit = 300
    rows = (await db.execute(query.order_by(WasteRequest.id.desc(), CollectionZone.id.desc()).limit(limit + 1))).all()
    return {"truncated": len(rows) > limit, "items": [
        {"id": pickup.id, "zone_id": zone_id, "latitude": pickup.latitude, "longitude": pickup.longitude,
         "weight_kg": pickup.weight_kg, "status": pickup.status.value, "waste_type": pickup.waste_type.value,
         "address": pickup.address, "pickup_note": pickup.pickup_note}
        for pickup, zone_id in rows[:limit]
    ]}


async def _notify_zone_smes(zone_request_ids: list[int], text: str):
    """Отправляет Telegram-уведомление владельцам заявок зоны (фоновая задача)."""
    from database import async_session_maker
    from routers.telegram_bot import send_notification

    if not settings.TELEGRAM_BOT_TOKEN:
        return
    async with async_session_maker() as db:
        result = await db.execute(
            select(User.telegram_chat_id)
            .join(WasteRequest, WasteRequest.sme_id == User.id)
            .where(
                WasteRequest.id.in_(zone_request_ids),
                User.telegram_chat_id.isnot(None),
            )
            .distinct()
        )
        chat_ids = [row[0] for row in result.all()]
    for chat_id in chat_ids:
        await send_notification(chat_id, text)


@router.post("/zones/{zone_id}/assign")
async def assign_zone(
    zone_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER)),
):
    # Блокируем строку, чтобы два переработчика не взяли одну зону одновременно
    result = await db.execute(
        select(CollectionZone).where(CollectionZone.id == zone_id).with_for_update()
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Зона не найдена")
    if zone.status != ZoneStatus.OPEN:
        raise HTTPException(status_code=409, detail="Зона уже занята")
    zone.status = ZoneStatus.ASSIGNED
    zone.recycler_id = current_user.id
    request_ids = list(zone.request_ids or [])
    await db.execute(
        update(WasteRequest)
        .where(WasteRequest.id.in_(request_ids))
        .values(status=RequestStatus.ASSIGNED)
    )
    await db.commit()
    background_tasks.add_task(compute_route_for_zone, zone_id)
    background_tasks.add_task(
        _notify_zone_smes,
        request_ids,
        f"🚚 QOSYU: вывоз назначен!\n\nПереработчик «{current_user.company_name}» "
        f"взял вашу зону сбора #{zone_id} в работу. Подготовьте вторсырьё к передаче.",
    )
    return {"message": "Зона закреплена за вами"}


@router.get("/zones/{zone_id}/route", dependencies=[Depends(rate_limit("route-preview", limit=30, window_seconds=60)), Depends(rate_limit("route-hour", limit=60, window_seconds=3600))])
async def zone_route(
    zone_id: int,
    start_lat: float | None = Query(None, ge=-90, le=90),
    start_lon: float | None = Query(None, ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER, UserRole.ADMIN)),
):
    """Оптимальный маршрут объезда точек зоны: порядок, дистанция, ETA, геометрия."""
    if (start_lat is None) != (start_lon is None):
        raise HTTPException(status_code=422, detail="Укажите обе координаты начала маршрута")
    if current_user.role not in (UserRole.RECYCLER, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Маршрут доступен переработчику")
    zone = await db.scalar(select(CollectionZone).where(
        CollectionZone.id == zone_id, visible_zone_condition(current_user)
    ))
    if not zone:
        # Preserve the route API's distinction for existing callers.
        if await db.scalar(select(CollectionZone.id).where(CollectionZone.id == zone_id)):
            raise HTTPException(status_code=403, detail="Зона недоступна")
        raise HTTPException(status_code=404, detail="Зона не найдена")

    result = await db.execute(
        select(WasteRequest, User.company_name)
        .join(User, WasteRequest.sme_id == User.id)
        .join(CollectionZone, zone_has_request())
        .where(CollectionZone.id == zone_id, visible_zone_condition(current_user))
        .order_by(WasteRequest.id)
    )
    rows = result.all()
    if not rows or len(rows) != len(set(zone.request_ids or [])):
        raise HTTPException(status_code=409, detail="Состав зоны неполный; маршрут не построен")

    depot = (
        start_lat if start_lat is not None else settings.DEPOT_LAT,
        start_lon if start_lon is not None else settings.DEPOT_LON,
    )
    requests = [r for r, _ in rows]
    companies = {r.id: company for r, company in rows}
    stops = [(r.latitude, r.longitude) for r in requests]
    route = await compute_route(depot, stops, settings.OSRM_BASE_URL)

    ordered_stops = []
    for position, stop_index in enumerate(route["waypoint_order"], start=1):
        req = requests[stop_index]
        ordered_stops.append(
            {
                "order": position,
                "request_id": req.id,
                "lat": req.latitude,
                "lon": req.longitude,
                "waste_type": req.waste_type.value,
                "weight_kg": req.weight_kg,
                "company": companies.get(req.id),
                "address": req.address,
                "pickup_note": req.pickup_note,
            }
        )

    return {
        "zone_id": zone.id,
        "source": route["source"],
        "order_source": route.get("order_source", "osrm_trip" if route["source"] == "osrm" else "geographic"),
        "approximate": route["source"] not in ("osrm", "2gis"),
        "provider_warning": route.get("provider_warning"),
        "service_minutes_per_stop": 6,
        "start": {"lat": depot[0], "lon": depot[1]},
        "distance_km": round(route["distance_meters"] / 1000, 1),
        "duration_min": round(route["duration_seconds"] / 60),
        "total_weight_kg": zone.total_weight_kg,
        "stops": ordered_stops,
        "geometry": route["geometry"],
    }


@router.post("/zones/{zone_id}/complete")
async def complete_zone(
    zone_id: int,
    background_tasks: BackgroundTasks,
    data: ZoneComplete | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER)),
):
    result = await db.execute(
        select(CollectionZone).where(CollectionZone.id == zone_id).with_for_update()
    )
    zone = result.scalar_one_or_none()
    if not zone or zone.recycler_id != current_user.id:
        raise HTTPException(status_code=404, detail="Зона не найдена или закреплена не за вами")
    if zone.status not in (ZoneStatus.ASSIGNED, ZoneStatus.IN_PROGRESS):
        raise HTTPException(status_code=409, detail="Зона не находится в работе")
    request_ids = list(zone.request_ids or [])
    materials = (await db.execute(select(WasteRequest.waste_type, WasteRequest.weight_kg)
                                  .where(WasteRequest.id.in_(request_ids)))).all()
    await db.execute(
        update(WasteRequest)
        .where(WasteRequest.id.in_(request_ids))
        .values(status=RequestStatus.COLLECTED)
    )
    zone.status = ZoneStatus.COMPLETED
    actual_weight = data.actual_weight_kg if data else None
    cardboard_kg = sum(weight for material, weight in materials if material == WasteType.CARDBOARD)
    if actual_weight is not None and materials and all(material == WasteType.CARDBOARD for material, _ in materials):
        cardboard_kg = actual_weight
    co2_saved = calculate_co2_saved(cardboard_kg)
    event = CollectionEvent(
        zone_id=zone.id,
        recycler_id=current_user.id,
        start_time=zone.created_at,
        end_time=func.now(),
        co2_saved_kg=co2_saved,
        actual_weight_kg=actual_weight,
    )
    db.add(event)
    await db.commit()
    background_tasks.add_task(
        _notify_zone_smes,
        request_ids,
        f"✅ QOSYU: вторсырьё вывезено!\n\nЗона #{zone_id} завершена. "
        f"Модельный эквивалент для зоны: {co2_saved} кг CO₂-экв.\n{CO2E_FORMULA_RU}\n"
        "Спасибо, что перерабатываете!",
    )
    return {"message": "Зона завершена, ESG-метрики обновлены"}


@router.get("/zones/my", response_model=list[CollectionZoneOut])
async def my_zones(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER)),
):
    result = await db.execute(
        select(CollectionZone)
        .where(
            CollectionZone.recycler_id == current_user.id,
            CollectionZone.status.in_([ZoneStatus.ASSIGNED, ZoneStatus.IN_PROGRESS]),
        )
        .order_by(CollectionZone.created_at.desc())
    )
    zones = result.scalars().all()
    return [
        CollectionZoneOut(
            id=z.id,
            centroid_lat=z.centroid_lat,
            centroid_lon=z.centroid_lon,
            radius_km=z.radius_km,
            total_weight_kg=z.total_weight_kg,
            request_count=len(z.request_ids or []),
            status=z.status,
            optimized_route=z.optimized_route,
        )
        for z in zones
    ]
