from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from geoalchemy2 import Geometry
from database import get_db
from models import User, WasteRequest, RequestStatus
from schemas import WasteRequestCreate, WasteRequestOut
from dependencies import get_current_user

router = APIRouter()

@router.post("/create", response_model=WasteRequestOut)
async def create_request(
    req: WasteRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "sme":
        raise HTTPException(status_code=403, detail="Only SME users can create requests")
    new_req = WasteRequest(
        sme_id=current_user.id,
        waste_type=req.waste_type,
        weight_kg=req.weight_kg,
        latitude=req.latitude,
        longitude=req.longitude,
        location_geom=func.ST_SetSRID(func.ST_MakePoint(req.longitude, req.latitude), 4326),
        status=RequestStatus.PENDING
    )
    db.add(new_req)
    await db.commit()
    await db.refresh(new_req)
    return new_req

@router.get("/my", response_model=list[WasteRequestOut])
async def my_requests(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(WasteRequest).where(WasteRequest.sme_id == current_user.id))
    return result.scalars().all()