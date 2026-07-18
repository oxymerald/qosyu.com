from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from models import MarketplaceListing, MarketplaceOrder, User, WasteType
from schemas import ListingCreate, OrderCreate, OrderStatusUpdate
from security import rate_limit

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


def _listing_out(l: MarketplaceListing, detailed: bool = False) -> dict:
    data = {
        "id": l.id,
        "waste_type": l.waste_type.value,
        "price_per_kg": l.price_per_kg,
        "min_kg": l.min_kg,
        "available_kg": l.available_kg,
        "description": l.description,
        "user_id": l.user_id,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }
    if detailed:
        data.update(
            {
                "max_kg": l.max_kg,
                "location_lat": l.location_lat,
                "location_lon": l.location_lon,
                "views": l.views,
                "expires_at": l.expires_at.isoformat() if l.expires_at else None,
            }
        )
    return data


@router.post(
    "/listings",
    status_code=201,
    dependencies=[Depends(rate_limit("create-listing", limit=20, window_seconds=3600))],
)
async def create_listing(
    listing: ListingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_listing = MarketplaceListing(user_id=current_user.id, **listing.model_dump())
    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return {"id": new_listing.id, "message": "Объявление создано"}


@router.get("/listings")
async def get_listings(
    waste_type: WasteType | None = None,
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(MarketplaceListing).where(MarketplaceListing.is_active == True)  # noqa: E712
    if waste_type:
        query = query.where(MarketplaceListing.waste_type == waste_type)
    if min_price is not None:
        query = query.where(MarketplaceListing.price_per_kg >= min_price)
    if max_price is not None:
        query = query.where(MarketplaceListing.price_per_kg <= max_price)
    query = query.order_by(MarketplaceListing.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [_listing_out(l) for l in result.scalars().all()]


@router.get("/listings/{listing_id}")
async def get_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing or not listing.is_active:
        raise HTTPException(status_code=404, detail="Объявление не найдено")
    listing.views = (listing.views or 0) + 1
    await db.commit()
    return _listing_out(listing, detailed=True)


@router.post(
    "/orders",
    status_code=201,
    dependencies=[Depends(rate_limit("create-order", limit=30, window_seconds=3600))],
)
async def create_order(
    order: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Блокировка строки объявления защищает available_kg от гонки двух заказов
    result = await db.execute(
        select(MarketplaceListing)
        .where(MarketplaceListing.id == order.listing_id)
        .with_for_update()
    )
    listing = result.scalar_one_or_none()
    if not listing or not listing.is_active:
        raise HTTPException(status_code=404, detail="Объявление недоступно")
    if listing.user_id == current_user.id:
        raise HTTPException(status_code=409, detail="Нельзя заказать по собственному объявлению")
    if order.quantity_kg < listing.min_kg:
        raise HTTPException(status_code=422, detail=f"Минимальная партия — {listing.min_kg} кг")
    if listing.max_kg and order.quantity_kg > listing.max_kg:
        raise HTTPException(status_code=422, detail=f"Максимальная партия — {listing.max_kg} кг")
    if listing.available_kg is not None and order.quantity_kg > listing.available_kg:
        raise HTTPException(status_code=409, detail="Недостаточно доступного объёма")

    new_order = MarketplaceOrder(
        listing_id=order.listing_id,
        buyer_id=current_user.id,
        seller_id=listing.user_id,
        quantity_kg=order.quantity_kg,
        total_price=round(order.quantity_kg * listing.price_per_kg, 2),
        status="pending",
    )
    db.add(new_order)
    if listing.available_kg is not None:
        listing.available_kg -= order.quantity_kg
    await db.commit()
    await db.refresh(new_order)
    return {"order_id": new_order.id, "total": new_order.total_price}


@router.get("/orders/my")
async def get_my_orders(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MarketplaceOrder, MarketplaceListing)
        .join(MarketplaceListing, MarketplaceOrder.listing_id == MarketplaceListing.id)
        .where(
            (MarketplaceOrder.buyer_id == current_user.id)
            | (MarketplaceOrder.seller_id == current_user.id)
        )
        .order_by(MarketplaceOrder.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    return [
        {
            "id": o.id,
            "listing_id": o.listing_id,
            "waste_type": l.waste_type.value,
            "quantity_kg": o.quantity_kg,
            "total_price": o.total_price,
            "status": o.status,
            "is_seller": o.seller_id == current_user.id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o, l in rows
    ]


# Разрешённые переходы: кто и из какого статуса может перевести заказ
_TRANSITIONS = {
    "seller": {"accepted": ["pending"], "completed": ["accepted"], "cancelled": ["pending", "accepted"]},
    "buyer": {"cancelled": ["pending"]},
}


@router.put("/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MarketplaceOrder).where(MarketplaceOrder.id == order_id).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order or (order.seller_id != current_user.id and order.buyer_id != current_user.id):
        raise HTTPException(status_code=404, detail="Заказ не найден")

    role = "seller" if order.seller_id == current_user.id else "buyer"
    allowed_from = _TRANSITIONS[role].get(data.status, [])
    if order.status not in allowed_from:
        raise HTTPException(
            status_code=409,
            detail=f"Нельзя перевести заказ из статуса «{order.status}» в «{data.status}»",
        )

    if data.status == "cancelled":
        # Возвращаем зарезервированный объём в объявление
        listing = await db.get(MarketplaceListing, order.listing_id)
        if listing and listing.available_kg is not None:
            listing.available_kg += order.quantity_kg

    order.status = data.status
    await db.commit()
    return {"status": data.status}
