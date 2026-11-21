"""Gemini assistant with read-only map tools and rule-based operational insights.

Without credentials the application works and operational insights use rules.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import get_current_user, require_roles
from models import (
    CollectionZone,
    RequestStatus,
    User,
    UserRole,
    WasteRequest,
    ZoneStatus,
)
from security import rate_limit
from services import ai_tools, gemini

router = APIRouter(prefix="/ai", tags=["ai"])


def _ai_available() -> bool:
    return bool(settings.GEMINI_API_KEY.strip())


class AssistantMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class MapStart(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class AssistantIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[AssistantMessage] = Field(default_factory=list, max_length=10)
    map_start: MapStart | None = None
    selected_zone_id: int | None = Field(default=None, gt=0)


class MapSelection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


@router.post("/map/{kind}")
async def map_selection(
    kind: Literal["requests", "zones"],
    data: MapSelection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ai_tools.map_items(kind, data.ids, db, current_user)


@router.get("/status")
async def ai_status():
    available = _ai_available()
    return {
        "available": available,
        "provider": "gemini",
        "model": settings.GEMINI_MODEL if available else None,
        "map_tools": available,
    }


@router.post(
    "/assistant",
    dependencies=[Depends(rate_limit("ai-assistant", limit=30, window_seconds=3600))],
)
async def assistant(
    data: AssistantIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await gemini.assistant(data, db, current_user)


@router.get(
    "/insights",
    dependencies=[Depends(rate_limit("ai-insights", limit=20, window_seconds=3600))],
)
async def insights(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.ADMIN)),
):
    """Операционная аналитика на базе правил (без расхода внешней AI-квоты)."""
    pending = (
        await db.execute(
            select(
                func.count(WasteRequest.id),
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            ).where(WasteRequest.status == RequestStatus.PENDING)
        )
    ).one()
    pending_count, pending_weight = pending[0], float(pending[1])

    top_type_row = (
        await db.execute(
            select(
                WasteRequest.waste_type,
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            )
            .group_by(WasteRequest.waste_type)
            .order_by(func.sum(WasteRequest.weight_kg).desc())
            .limit(1)
        )
    ).first()
    top_type = top_type_row[0].value if top_type_row else None
    open_zones = (
        await db.execute(
            select(func.count(CollectionZone.id)).where(
                CollectionZone.status == ZoneStatus.OPEN
            )
        )
    ).scalar() or 0

    stats = {
        "pending_requests": pending_count,
        "pending_weight_kg": round(pending_weight, 1),
        "open_zones": open_zones,
        "top_waste_type": top_type,
    }

    recommendations = []
    if pending_count >= 2 and open_zones == 0:
        recommendations.append(
            f"Накопилось {pending_count} заявок ({round(pending_weight)} кг) — запустите "
            "кластеризацию, чтобы сформировать зоны сбора."
        )
    if open_zones > 0:
        recommendations.append(
            f"Открыто {open_zones} зон — возьмите ближайшую в работу, маршрут построится автоматически."
        )
    if top_type:
        recommendations.append(
            f"Больше всего сырья по типу «{top_type}» — имеет смысл договориться с профильным переработчиком."
        )
    if not recommendations:
        recommendations.append("Пока недостаточно данных — создайте несколько заявок для аналитики.")

    return {"stats": stats, "recommendations": recommendations, "source": "rules"}
