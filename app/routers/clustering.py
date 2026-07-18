from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import WasteRequest, RequestStatus, CollectionZone, ZoneStatus
from services.geo import cluster_requests, create_collection_zones, optimize_route
from dependencies import get_current_user
from config import settings

router = APIRouter()

@router.post("/generate-zones")
async def generate_zones(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user)
):
    result = await db.execute(select(WasteRequest).where(WasteRequest.status == RequestStatus.PENDING))
    pending = result.scalars().all()
    if len(pending) < 2:
        raise HTTPException(status_code=400, detail="Not enough pending requests to cluster")
    zones = await create_collection_zones(db, pending)
    for req in pending:
        req.status = RequestStatus.CLUSTERED
    await db.commit()
    for zone in zones:
        background_tasks.add_task(compute_route_for_zone, zone.id)
    return {"message": f"Created {len(zones)} collection zones", "zone_ids": [z.id for z in zones]}

async def compute_route_for_zone(zone_id: int):
    from database import async_session_maker
    async with async_session_maker() as db:
        result = await db.execute(select(CollectionZone).where(CollectionZone.id == zone_id))
        zone = result.scalar_one()
        reqs_result = await db.execute(select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids)))
        zone.requests = reqs_result.scalars().all()
        await optimize_route(zone, settings.OSRM_BASE_URL)
        await db.commit()

@router.get("/zones/open", response_model=list[dict])
async def list_open_zones(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CollectionZone).where(CollectionZone.status == ZoneStatus.OPEN))
    zones = result.scalars().all()
    return [{"id": z.id, "centroid_lat": z.centroid_lat, "centroid_lon": z.centroid_lon,
             "total_weight_kg": z.total_weight_kg, "request_count": len(z.request_ids)} for z in zones]