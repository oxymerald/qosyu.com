from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database import get_db
from models import WasteRequest, User, RequestStatus
from dependencies import get_current_user
from datetime import date, timedelta

router = APIRouter()

@router.get("/esg/sme")
async def sme_esg(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(func.sum(WasteRequest.weight_kg))
        .where(WasteRequest.sme_id == current_user.id, WasteRequest.status == RequestStatus.COLLECTED)
    )
    total_recycled = result.scalar() or 0.0
    co2_saved = total_recycled * 0.5
    return {
        "company": current_user.company_name,
        "total_recycled_kg": total_recycled,
        "co2_saved_kg": co2_saved,
        "equivalent_trees": round(co2_saved / 22.0, 1)
    }

@router.get("/esg/platform")
async def platform_esg(db: AsyncSession = Depends(get_db)):
    thirty_days_ago = date.today() - timedelta(days=30)
    result = await db.execute(
        select(func.sum(WasteRequest.weight_kg))
        .where(WasteRequest.status == RequestStatus.COLLECTED, WasteRequest.created_at >= thirty_days_ago)
    )
    total = result.scalar() or 0.0
    return {
        "period_days": 30,
        "total_waste_diverted_kg": total,
        "co2_saved_kg": total * 0.5,
        "landfill_avoided_kg": total
    }