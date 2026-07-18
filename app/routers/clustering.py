from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import get_current_user, require_roles
from models import CollectionZone, RequestStatus, UserRole, WasteRequest, ZoneStatus
from schemas import CollectionZoneOut
from security import rate_limit
from services.geo import create_collection_zones, optimize_route

router = APIRouter()


@router.post(
    "/generate-zones",
    dependencies=[Depends(rate_limit("generate-zones", limit=10, window_seconds=600))],
)
async def generate_zones(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.ADMIN)),
):
    result = await db.execute(
        select(WasteRequest).where(WasteRequest.status == RequestStatus.PENDING)
    )
    pending = result.scalars().all()
    if len(pending) < 2:
        raise HTTPException(
            status_code=409, detail="Недостаточно заявок для кластеризации (нужно минимум 2)"
        )
    zones = await create_collection_zones(db, pending)
    clustered_ids = {rid for z in zones for rid in z.request_ids}
    for req in pending:
        if req.id in clustered_ids:
            req.status = RequestStatus.CLUSTERED
    await db.commit()
    for zone in zones:
        background_tasks.add_task(compute_route_for_zone, zone.id)
    return {"message": f"Создано зон: {len(zones)}", "zone_ids": [z.id for z in zones]}


async def compute_route_for_zone(zone_id: int):
    from database import async_session_maker

    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(CollectionZone).where(CollectionZone.id == zone_id)
            )
            zone = result.scalar_one_or_none()
            if zone is None:
                return
            reqs_result = await db.execute(
                select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids))
            )
            requests = reqs_result.scalars().all()
            await optimize_route(zone, requests, settings.OSRM_BASE_URL)
            await db.commit()
    except Exception:
        # Маршрут — необязательное улучшение: зона остаётся рабочей и без него
        pass


@router.get("/zones/open", response_model=list[CollectionZoneOut])
async def list_open_zones(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(CollectionZone).where(CollectionZone.status == ZoneStatus.OPEN)
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
