from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_roles
from models import (
    CollectionZone,
    MarketplaceOrder,
    RequestStatus,
    User,
    UserRole,
    WasteRequest,
    ZoneStatus,
)
from services.esg import calculate_co2_saved

router = APIRouter(prefix="/admin", tags=["admin"])

admin_only = Depends(require_roles(UserRole.ADMIN))


@router.get("/stats", dependencies=[admin_only])
async def platform_stats(db: AsyncSession = Depends(get_db)):
    users_by_role = dict(
        (await db.execute(select(User.role, func.count(User.id)).group_by(User.role))).all()
    )
    requests_by_status = dict(
        (
            await db.execute(
                select(WasteRequest.status, func.count(WasteRequest.id)).group_by(
                    WasteRequest.status
                )
            )
        ).all()
    )
    zones_by_status = dict(
        (
            await db.execute(
                select(CollectionZone.status, func.count(CollectionZone.id)).group_by(
                    CollectionZone.status
                )
            )
        ).all()
    )
    collected_weight = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(WasteRequest.weight_kg), 0.0)).where(
                    WasteRequest.status.in_([RequestStatus.COLLECTED, RequestStatus.VERIFIED])
                )
            )
        ).scalar()
        or 0.0
    )
    orders_count = (
        await db.execute(select(func.count(MarketplaceOrder.id)))
    ).scalar() or 0

    # Серия за 14 дней: количество заявок и вес по дням
    since = date.today() - timedelta(days=13)
    day_col = func.date(WasteRequest.created_at)
    series_rows = (
        await db.execute(
            select(
                day_col.label("day"),
                func.count(WasteRequest.id),
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            )
            .where(WasteRequest.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()
    by_day = {str(row[0]): {"count": row[1], "weight_kg": float(row[2])} for row in series_rows}
    series = []
    for offset in range(14):
        day = since + timedelta(days=offset)
        entry = by_day.get(str(day), {"count": 0, "weight_kg": 0.0})
        series.append({"date": str(day), **entry})

    waste_rows = (
        await db.execute(
            select(
                WasteRequest.waste_type,
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            ).group_by(WasteRequest.waste_type)
        )
    ).all()

    return {
        "users": {
            "total": sum(users_by_role.values()),
            "sme": users_by_role.get(UserRole.SME, 0),
            "recycler": users_by_role.get(UserRole.RECYCLER, 0),
            "admin": users_by_role.get(UserRole.ADMIN, 0),
        },
        "requests": {
            "total": sum(requests_by_status.values()),
            "by_status": {k.value: v for k, v in requests_by_status.items()},
        },
        "zones": {
            "total": sum(zones_by_status.values()),
            "open": zones_by_status.get(ZoneStatus.OPEN, 0),
            "in_work": zones_by_status.get(ZoneStatus.ASSIGNED, 0)
            + zones_by_status.get(ZoneStatus.IN_PROGRESS, 0),
            "completed": zones_by_status.get(ZoneStatus.COMPLETED, 0),
        },
        "esg": {
            "collected_kg": round(collected_weight, 1),
            "co2_saved_kg": round(calculate_co2_saved(collected_weight), 1),
        },
        "orders_total": orders_count,
        "requests_series_14d": series,
        "waste_distribution": [
            {"waste_type": wt.value, "weight_kg": round(float(weight), 1)}
            for wt, weight in waste_rows
        ],
    }


@router.get("/users", dependencies=[admin_only])
async def list_users(
    search: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc())
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(User.email.ilike(pattern) | User.company_name.ilike(pattern))
    result = await db.execute(query.limit(limit).offset(offset))
    return [
        {
            "id": u.id,
            "email": u.email,
            "company_name": u.company_name,
            "role": u.role.value,
            "is_active": u.is_active,
            "telegram_linked": u.telegram_chat_id is not None,
            "rating_avg": u.rating_avg or 0,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in result.scalars().all()
    ]


class UserModeration(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}", dependencies=[])
async def moderate_user(
    user_id: int,
    data: UserModeration,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == current_admin.id:
        raise HTTPException(status_code=409, detail="Нельзя заблокировать самого себя")
    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=409, detail="Нельзя блокировать администраторов")
    user.is_active = data.is_active
    await db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.get("/requests", dependencies=[admin_only])
async def list_requests(
    status: RequestStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(WasteRequest, User.company_name)
        .join(User, WasteRequest.sme_id == User.id)
        .order_by(WasteRequest.created_at.desc())
    )
    if status:
        query = query.where(WasteRequest.status == status)
    result = await db.execute(query.limit(limit).offset(offset))
    return [
        {
            "id": r.id,
            "company": company,
            "waste_type": r.waste_type.value,
            "weight_kg": r.weight_kg,
            "status": r.status.value,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, company in result.all()
    ]
