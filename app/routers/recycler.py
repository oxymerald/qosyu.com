from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter()


@router.post("/zones/{zone_id}/assign")
async def assign_zone(
    zone_id: int,
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
    await db.execute(
        update(WasteRequest)
        .where(WasteRequest.id.in_(zone.request_ids or []))
        .values(status=RequestStatus.ASSIGNED)
    )
    await db.commit()
    return {"message": "Зона закреплена за вами"}


@router.post("/zones/{zone_id}/complete")
async def complete_zone(
    zone_id: int,
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
    await db.execute(
        update(WasteRequest)
        .where(WasteRequest.id.in_(zone.request_ids or []))
        .values(status=RequestStatus.COLLECTED)
    )
    zone.status = ZoneStatus.COMPLETED
    actual_weight = data.actual_weight_kg if data else None
    collected_weight = actual_weight or zone.total_weight_kg
    event = CollectionEvent(
        zone_id=zone.id,
        recycler_id=current_user.id,
        start_time=zone.created_at,
        end_time=func.now(),
        co2_saved_kg=calculate_co2_saved(collected_weight),
        actual_weight_kg=actual_weight,
    )
    db.add(event)
    await db.commit()
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
