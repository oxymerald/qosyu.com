from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from auth import validate_password_strength
from models import RequestStatus, UserRole, WasteType, ZoneStatus


# ========== Пользователи и авторизация ==========

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    company_name: str = Field(..., min_length=2, max_length=120)
    # Роль admin намеренно недоступна при самостоятельной регистрации
    role: Literal[UserRole.SME, UserRole.RECYCLER] = UserRole.SME

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("company_name")
    @classmethod
    def strip_company(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Название компании слишком короткое")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        error = validate_password_strength(v)
        if error:
            raise ValueError(error)
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        error = validate_password_strength(v)
        if error:
            raise ValueError(error)
        return v


class UserOut(BaseModel):
    id: int
    email: str
    company_name: Optional[str] = None
    role: UserRole
    rating_avg: float = 0.0

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ========== Заявки ==========

class WasteRequestCreate(BaseModel):
    waste_type: WasteType
    weight_kg: float = Field(..., gt=0, le=50_000)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class WasteRequestOut(BaseModel):
    id: int
    sme_id: int
    waste_type: WasteType
    weight_kg: float
    latitude: float
    longitude: float
    status: RequestStatus
    created_at: datetime

    class Config:
        from_attributes = True


class CollectionZoneOut(BaseModel):
    id: int
    centroid_lat: float
    centroid_lon: float
    radius_km: Optional[float] = None
    total_weight_kg: float
    request_count: int
    status: ZoneStatus
    optimized_route: Optional[dict] = None


# ========== Отзывы ==========

class ReviewCreate(BaseModel):
    recycler_id: int = Field(..., gt=0)
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    zone_id: Optional[int] = Field(None, gt=0)


class ReviewRespond(BaseModel):
    response: str = Field(..., min_length=1, max_length=2000)


# ========== Маркетплейс ==========

class ListingCreate(BaseModel):
    waste_type: WasteType
    price_per_kg: float = Field(..., gt=0, le=1_000_000)
    min_kg: float = Field(0, ge=0, le=50_000)
    max_kg: Optional[float] = Field(None, gt=0, le=50_000)
    available_kg: Optional[float] = Field(None, gt=0, le=1_000_000)
    description: Optional[str] = Field(None, max_length=2000)
    location_lat: Optional[float] = Field(None, ge=-90, le=90)
    location_lon: Optional[float] = Field(None, ge=-180, le=180)
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def check_ranges(self):
        if self.max_kg is not None and self.min_kg > self.max_kg:
            raise ValueError("min_kg не может быть больше max_kg")
        if self.expires_at is not None:
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                raise ValueError("expires_at должен быть в будущем")
        return self


class OrderCreate(BaseModel):
    listing_id: int = Field(..., gt=0)
    quantity_kg: float = Field(..., gt=0, le=1_000_000)


class OrderStatusUpdate(BaseModel):
    status: Literal["accepted", "cancelled", "completed"]


# ========== Push-уведомления ==========

class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=512)
    auth: str = Field(..., min_length=1, max_length=512)


class PushSubscribe(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=1000)
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def check_endpoint(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("endpoint должен быть https URL")
        return v


class PushUnsubscribe(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=1000)


# ========== Зоны (переработчик) ==========

class ZoneComplete(BaseModel):
    actual_weight_kg: Optional[float] = Field(None, gt=0, le=1_000_000)
