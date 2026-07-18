from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models import CollectionZone, ZoneStatus, User, CollectionEvent, WasteRequest, RequestStatus
from dependencies import get_current_user

router = APIRouter()

@router.post("/zones/{zone_id}/assign")
async def assign_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "recycler":
        raise HTTPException(status_code=403, detail="Only recyclers can assign zones")
    result = await db.execute(select(CollectionZone).where(CollectionZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone or zone.status != ZoneStatus.OPEN:
        raise HTTPException(status_code=400, detail="Zone not available")
    zone.status = ZoneStatus.ASSIGNED
    zone.recycler_id = current_user.id
    await db.commit()
    return {"message": "Zone assigned successfully"}

@router.post("/zones/{zone_id}/complete")
async def complete_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(CollectionZone).where(CollectionZone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone or zone.recycler_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    for req_id in zone.request_ids:
        req_result = await db.execute(select(WasteRequest).where(WasteRequest.id == req_id))
        req = req_result.scalar_one()
        req.status = RequestStatus.COLLECTED
    zone.status = ZoneStatus.COMPLETED
    event = CollectionEvent(
        zone_id=zone.id,
        recycler_id=current_user.id,
        start_time=zone.created_at,
        end_time=func.now(),
        co2_saved_kg=zone.total_weight_kg * 0.5
    )
    db.add(event)
    await db.commit()
    return {"message": "Zone completed, ESG data updated"}