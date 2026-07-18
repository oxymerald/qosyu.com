from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from models import RequestStatus, User, WasteRequest
from security import rate_limit
from services.esg import CO2_PER_KG, calculate_co2_saved

router = APIRouter()


@router.get("/esg/sme")
async def sme_esg(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(func.coalesce(func.sum(WasteRequest.weight_kg), 0.0)).where(
            WasteRequest.sme_id == current_user.id,
            WasteRequest.status.in_([RequestStatus.COLLECTED, RequestStatus.VERIFIED]),
        )
    )
    total_recycled = float(result.scalar() or 0.0)
    co2_saved = calculate_co2_saved(total_recycled)
    return {
        "company": current_user.company_name,
        "total_recycled_kg": round(total_recycled, 1),
        "co2_saved_kg": round(co2_saved, 1),
        "equivalent_trees": round(co2_saved / 22.0, 1),
        "co2_factor": CO2_PER_KG,
    }


@router.get(
    "/esg/platform",
    dependencies=[Depends(rate_limit("esg-platform", limit=60, window_seconds=60))],
)
async def platform_esg(db: AsyncSession = Depends(get_db)):
    thirty_days_ago = date.today() - timedelta(days=30)
    result = await db.execute(
        select(func.coalesce(func.sum(WasteRequest.weight_kg), 0.0)).where(
            WasteRequest.status.in_([RequestStatus.COLLECTED, RequestStatus.VERIFIED]),
            WasteRequest.created_at >= thirty_days_ago,
        )
    )
    total = float(result.scalar() or 0.0)
    return {
        "period_days": 30,
        "total_waste_diverted_kg": round(total, 1),
        "co2_saved_kg": round(calculate_co2_saved(total), 1),
        "landfill_avoided_kg": round(total, 1),
    }
