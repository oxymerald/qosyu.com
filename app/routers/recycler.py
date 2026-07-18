from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select, update
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
    ZoneStatus,
)
from schemas import CollectionZoneOut, ZoneComplete
from services.esg import calculate_co2_saved
from services.geo import compute_route

router = APIRouter()


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


async def _compute_zone_route_task(zone_id: int):
    """Пересчитывает и сохраняет маршрут зоны (фоновая задача)."""
    from database import async_session_maker
    from services.geo import optimize_route

    try:
        async with async_session_maker() as db:
            result = await db.execute(select(CollectionZone).where(CollectionZone.id == zone_id))
            zone = result.scalar_one_or_none()
            if zone is None:
                return
            reqs = await db.execute(
                select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids or []))
            )
            await optimize_route(zone, reqs.scalars().all(), settings.OSRM_BASE_URL)
            await db.commit()
    except Exception:
        pass  # маршрут можно запросить и на лету через GET /zones/{id}/route


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
    background_tasks.add_task(_compute_zone_route_task, zone_id)
    background_tasks.add_task(
        _notify_zone_smes,
        request_ids,
        f"🚚 QOSYU: вывоз назначен!\n\nПереработчик «{current_user.company_name}» "
        f"взял вашу зону сбора #{zone_id} в работу. Подготовьте вторсырьё к передаче.",
    )
    return {"message": "Зона закреплена за вами"}


@router.get("/zones/{zone_id}/route")
async def zone_route(
    zone_id: int,
    start_lat: float | None = Query(None, ge=-90, le=90),
    start_lon: float | None = Query(None, ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER, UserRole.ADMIN)),
):
    """Оптимальный маршрут объезда точек зоны: порядок, дистанция, ETA, геометрия."""
    zone = await db.get(CollectionZone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Зона не найдена")
    if (
        current_user.role == UserRole.RECYCLER
        and zone.status != ZoneStatus.OPEN
        and zone.recycler_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Зона закреплена за другим переработчиком")

    result = await db.execute(
        select(WasteRequest, User.company_name)
        .join(User, WasteRequest.sme_id == User.id)
        .where(WasteRequest.id.in_(zone.request_ids or []))
    )
    rows = result.all()
    if not rows:
        raise HTTPException(status_code=409, detail="В зоне нет заявок")

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
            }
        )

    return {
        "zone_id": zone.id,
        "source": route["source"],
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
    await db.execute(
        update(WasteRequest)
        .where(WasteRequest.id.in_(request_ids))
        .values(status=RequestStatus.COLLECTED)
    )
    zone.status = ZoneStatus.COMPLETED
    actual_weight = data.actual_weight_kg if data else None
    collected_weight = actual_weight or zone.total_weight_kg
    co2_saved = calculate_co2_saved(collected_weight)
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
        f"Ваш ESG-отчёт обновлён: +{round(co2_saved, 1)} кг CO₂ сэкономлено. "
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
