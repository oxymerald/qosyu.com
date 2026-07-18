from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_roles
from models import CollectionZone, Review, User, UserRole, WasteRequest, ZoneStatus
from schemas import ReviewCreate, ReviewRespond
from security import rate_limit

router = APIRouter(prefix="/reviews", tags=["reviews"])


async def _refresh_rating(db: AsyncSession, recycler_id: int):
    avg = await db.execute(
        select(func.avg(Review.rating)).where(Review.to_user_id == recycler_id)
    )
    await db.execute(
        update(User).where(User.id == recycler_id).values(rating_avg=float(avg.scalar() or 0))
    )


@router.post(
    "/",
    status_code=201,
    dependencies=[Depends(rate_limit("create-review", limit=10, window_seconds=3600))],
)
async def create_review(
    review: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SME)),
):
    recycler = await db.get(User, review.recycler_id)
    if not recycler or recycler.role != UserRole.RECYCLER:
        raise HTTPException(status_code=404, detail="Переработчик не найден")

    if review.zone_id:
        zone = await db.get(CollectionZone, review.zone_id)
        if not zone or zone.status != ZoneStatus.COMPLETED:
            raise HTTPException(status_code=409, detail="Зона ещё не завершена")
        if zone.recycler_id != review.recycler_id:
            raise HTTPException(status_code=409, detail="Эту зону обслуживал другой переработчик")
        reqs = await db.execute(
            select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids or []))
        )
        if not any(r.sme_id == current_user.id for r in reqs.scalars()):
            raise HTTPException(status_code=403, detail="Ваших заявок в этой зоне не было")
        duplicate = await db.execute(
            select(Review).where(
                Review.from_user_id == current_user.id, Review.zone_id == review.zone_id
            )
        )
        if duplicate.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Отзыв по этой зоне уже оставлен")

    new_review = Review(
        from_user_id=current_user.id,
        to_user_id=review.recycler_id,
        rating=review.rating,
        comment=review.comment,
        zone_id=review.zone_id,
        is_verified=bool(review.zone_id),
    )
    db.add(new_review)
    await db.flush()
    await _refresh_rating(db, review.recycler_id)
    await db.commit()
    return {"id": new_review.id}


@router.get("/{recycler_id}")
async def get_reviews(
    recycler_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review)
        .where(Review.to_user_id == recycler_id)
        .order_by(Review.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    reviews = result.scalars().all()
    avg = await db.execute(
        select(func.avg(Review.rating)).where(Review.to_user_id == recycler_id)
    )
    return {
        "reviews": [
            {
                "id": r.id,
                "rating": r.rating,
                "comment": r.comment,
                "recycler_response": r.recycler_response,
                "date": r.created_at.isoformat() if r.created_at else None,
                "is_verified": r.is_verified,
            }
            for r in reviews
        ],
        "average": float(avg.scalar() or 0),
    }


@router.post("/{review_id}/respond")
async def respond_to_review(
    review_id: int,
    data: ReviewRespond,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.RECYCLER)),
):
    review = await db.get(Review, review_id)
    if not review or review.to_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Отзыв не найден")
    review.recycler_response = data.response
    review.response_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
