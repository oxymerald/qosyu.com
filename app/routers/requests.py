from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_roles
from models import RequestStatus, User, UserRole, WasteRequest
from schemas import WasteRequestCreate, WasteRequestOut
from security import rate_limit

router = APIRouter()


@router.post(
    "/create",
    response_model=WasteRequestOut,
    status_code=201,
    dependencies=[Depends(rate_limit("create-request", limit=30, window_seconds=3600))],
)
async def create_request(
    req: WasteRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SME)),
):
    new_req = WasteRequest(
        sme_id=current_user.id,
        waste_type=req.waste_type,
        weight_kg=req.weight_kg,
        latitude=req.latitude,
        longitude=req.longitude,
        location_geom=func.ST_SetSRID(func.ST_MakePoint(req.longitude, req.latitude), 4326),
        status=RequestStatus.PENDING,
    )
    db.add(new_req)
    await db.commit()
    await db.refresh(new_req)
    return new_req


@router.get("/my", response_model=list[WasteRequestOut])
async def my_requests(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WasteRequest)
        .where(WasteRequest.sme_id == current_user.id)
        .order_by(WasteRequest.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.delete("/{request_id}", status_code=200)
async def cancel_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(WasteRequest).where(WasteRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req or req.sme_id != current_user.id:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if req.status != RequestStatus.PENDING:
        raise HTTPException(
            status_code=409, detail="Можно отменить только заявку в статусе ожидания"
        )
    await db.delete(req)
    await db.commit()
    return {"message": "Заявка отменена"}
