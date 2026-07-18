from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import MarketplaceListing, MarketplaceOrder, User, WasteType
from schemas import ListingCreate, OrderCreate
from dependencies import get_current_user

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

@router.post("/listings")
async def create_listing(
    listing: ListingCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    new_listing = MarketplaceListing(
        user_id=current_user.id,
        waste_type=listing.waste_type,
        price_per_kg=listing.price_per_kg,
        min_kg=listing.min_kg,
        max_kg=listing.max_kg,
        available_kg=listing.available_kg,
        description=listing.description,
        location_lat=listing.location_lat,
        location_lon=listing.location_lon,
        expires_at=listing.expires_at
    )
    db.add(new_listing)
    await db.commit()
    await db.refresh(new_listing)
    return {"id": new_listing.id, "message": "Listing created"}

@router.get("/listings")
async def get_listings(
    waste_type: WasteType = None,
    min_price: float = None,
    max_price: float = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    query = select(MarketplaceListing).where(MarketplaceListing.is_active == True)
    if waste_type:
        query = query.where(MarketplaceListing.waste_type == waste_type)
    if min_price:
        query = query.where(MarketplaceListing.price_per_kg >= min_price)
    if max_price:
        query = query.where(MarketplaceListing.price_per_kg <= max_price)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    listings = result.scalars().all()
    return [
        {
            "id": l.id,
            "waste_type": l.waste_type.value,
            "price_per_kg": l.price_per_kg,
            "min_kg": l.min_kg,
            "available_kg": l.available_kg,
            "description": l.description,
            "user_id": l.user_id,
            "created_at": l.created_at.isoformat()
        } for l in listings
    ]

@router.get("/listings/{listing_id}")
async def get_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(404, "Not found")
    listing.views += 1
    await db.commit()
    return {
        "id": listing.id,
        "waste_type": listing.waste_type.value,
        "price_per_kg": listing.price_per_kg,
        "min_kg": listing.min_kg,
        "max_kg": listing.max_kg,
        "available_kg": listing.available_kg,
        "description": listing.description,
        "location_lat": listing.location_lat,
        "location_lon": listing.location_lon,
        "user_id": listing.user_id,
        "views": listing.views,
        "created_at": listing.created_at.isoformat(),
        "expires_at": listing.expires_at.isoformat() if listing.expires_at else None
    }

@router.post("/orders")
async def create_order(
    order: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    listing = await db.get(MarketplaceListing, order.listing_id)
    if not listing or not listing.is_active:
        raise HTTPException(400, "Listing not available")
    if order.quantity_kg < listing.min_kg:
        raise HTTPException(400, f"Minimum quantity is {listing.min_kg} kg")
    if listing.max_kg and order.quantity_kg > listing.max_kg:
        raise HTTPException(400, f"Maximum quantity is {listing.max_kg} kg")
    if listing.available_kg and order.quantity_kg > listing.available_kg:
        raise HTTPException(400, "Not enough available")
    
    new_order = MarketplaceOrder(
        listing_id=order.listing_id,
        buyer_id=current_user.id,
        seller_id=listing.user_id,
        quantity_kg=order.quantity_kg,
        total_price=order.quantity_kg * listing.price_per_kg,
        status="pending"
    )
    db.add(new_order)
    if listing.available_kg:
        listing.available_kg -= order.quantity_kg
    await db.commit()
    return {"order_id": new_order.id, "total": new_order.total_price}

@router.get("/orders/my")
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    result = await db.execute(
        select(MarketplaceOrder).where(
            (MarketplaceOrder.buyer_id == current_user.id) | (MarketplaceOrder.seller_id == current_user.id)
        ).order_by(MarketplaceOrder.created_at.desc())
    )
    orders = result.scalars().all()
    return [
        {
            "id": o.id,
            "listing_id": o.listing_id,
            "quantity_kg": o.quantity_kg,
            "total_price": o.total_price,
            "status": o.status,
            "created_at": o.created_at.isoformat()
        } for o in orders
    ]

@router.put("/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    order = await db.get(MarketplaceOrder, order_id)
    if not order or (order.seller_id != current_user.id and order.buyer_id != current_user.id):
        raise HTTPException(404, "Order not found")
    if status not in ["accepted", "cancelled", "completed"]:
        raise HTTPException(400, "Invalid status")
    order.status = status
    await db.commit()
    return {"status": status}