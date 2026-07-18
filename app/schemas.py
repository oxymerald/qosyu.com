from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from models import WasteType, RequestStatus, UserRole, ZoneStatus

class UserCreate(BaseModel):
    email: str
    password: str
    company_name: str
    role: UserRole

class UserOut(BaseModel):
    id: int
    email: str
    company_name: str
    role: UserRole

class Token(BaseModel):
    access_token: str
    token_type: str

class WasteRequestCreate(BaseModel):
    waste_type: WasteType
    weight_kg: float = Field(..., gt=0)
    latitude: float
    longitude: float

class WasteRequestOut(BaseModel):
    id: int
    sme_id: int
    waste_type: WasteType
    weight_kg: float
    latitude: float
    longitude: float
    status: RequestStatus
    created_at: datetime

class CollectionZoneOut(BaseModel):
    id: int
    centroid_lat: float
    centroid_lon: float
    total_weight_kg: float
    request_count: int
    status: ZoneStatus
    optimized_route: Optional[dict]

# ========== НОВЫЕ СХЕМЫ ==========

class ReviewCreate(BaseModel):
    recycler_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class ListingCreate(BaseModel):
    waste_type: WasteType
    price_per_kg: float = Field(..., gt=0)
    min_kg: float = 0
    max_kg: Optional[float] = None
    available_kg: Optional[float] = None
    description: Optional[str] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    expires_at: Optional[datetime] = None

class OrderCreate(BaseModel):
    listing_id: int
    quantity_kg: float = Field(..., gt=0)