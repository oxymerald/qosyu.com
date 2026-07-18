from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Review, User, CollectionZone, WasteRequest
from schemas import ReviewCreate
from dependencies import get_current_user
from datetime import datetime

router = APIRouter(prefix="/reviews", tags=["reviews"])

@router.post("/")
async def create_review(
    review: ReviewCreate,
    zone_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != "sme":
        raise HTTPException(403, "Only SME can leave reviews")
    
    if zone_id:
        zone = await db.get(CollectionZone, zone_id)
        if not zone or zone.status != "COMPLETED":
            raise HTTPException(400, "Zone not completed")
        reqs = await db.execute(select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids)))
        if not any(r.sme_id == current_user.id for r in reqs.scalars()):
            raise HTTPException(403, "Not your zone")
    
    new_review = Review(
        from_user_id=current_user.id,
        to_user_id=review.recycler_id,
        rating=review.rating,
        comment=review.comment,
        zone_id=zone_id,
        is_verified=bool(zone_id)
    )
    db.add(new_review)
    await db.commit()
    
    avg = await db.execute(select(func.avg(Review.rating)).where(Review.to_user_id == review.recycler_id))
    avg_val = avg.scalar() or 0
    await db.execute(update(User).where(User.id == review.recycler_id).values(rating_avg=float(avg_val)))
    await db.commit()
    
    return {"id": new_review.id}

@router.get("/{recycler_id}")
async def get_reviews(recycler_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Review).where(Review.to_user_id == recycler_id).order_by(Review.created_at.desc())
    )
    reviews = result.scalars().all()
    avg = await db.execute(select(func.avg(Review.rating)).where(Review.to_user_id == recycler_id))
    avg_rating = avg.scalar() or 0
    return {
        "reviews": [
            {
                "id": r.id,
                "rating": r.rating,
                "comment": r.comment,
                "recycler_response": r.recycler_response,
                "date": r.created_at.isoformat(),
                "is_verified": r.is_verified
            } for r in reviews
        ],
        "average": float(avg_rating)
    }

@router.post("/{review_id}/respond")
async def respond_to_review(
    review_id: int,
    response: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    review = await db.get(Review, review_id)
    if not review or review.to_user_id != current_user.id:
        raise HTTPException(404, "Not found")
    review.recycler_response = response
    review.response_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}