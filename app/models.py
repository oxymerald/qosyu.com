from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, ForeignKey, Boolean, JSON, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()

class UserRole(str, enum.Enum):
    SME = "sme"
    RECYCLER = "recycler"
    ADMIN = "admin"

class WasteType(str, enum.Enum):
    PLASTIC = "plastic"
    CARDBOARD = "cardboard"
    GLASS = "glass"
    METAL = "metal"
    ORGANIC = "organic"

class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    CLUSTERED = "clustered"
    ASSIGNED = "assigned"
    COLLECTED = "collected"
    VERIFIED = "verified"

class ZoneStatus(str, enum.Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    company_name = Column(String)
    role = Column(Enum(UserRole), default=UserRole.SME)
    is_active = Column(Boolean, default=True)
    telegram_chat_id = Column(BigInteger, nullable=True, unique=True)
    rating_avg = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WasteRequest(Base):
    __tablename__ = "waste_requests"
    id = Column(Integer, primary_key=True)
    sme_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    waste_type = Column(Enum(WasteType), nullable=False)
    weight_kg = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_geom = Column(Geometry('POINT', srid=4326), nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CollectionZone(Base):
    __tablename__ = "collection_zones"
    id = Column(Integer, primary_key=True)
    centroid_lat = Column(Float, nullable=False)
    centroid_lon = Column(Float, nullable=False)
    radius_km = Column(Float)
    total_weight_kg = Column(Float, default=0.0)
    request_ids = Column(JSON)
    recycler_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(Enum(ZoneStatus), default=ZoneStatus.OPEN)
    optimized_route = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CollectionEvent(Base):
    __tablename__ = "collection_events"
    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("collection_zones.id"))
    recycler_id = Column(Integer, ForeignKey("users.id"))
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True), nullable=True)
    co2_saved_kg = Column(Float, default=0.0)
    actual_weight_kg = Column(Float, nullable=True)

# ========== НОВЫЕ МОДЕЛИ ==========

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, server_default='false')
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(String, unique=True, nullable=False, index=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), onupdate=func.now())

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    images = Column(JSON, default=list)
    recycler_response = Column(Text, nullable=True)
    response_at = Column(DateTime(timezone=True), nullable=True)
    is_verified = Column(Boolean, default=False)
    zone_id = Column(Integer, ForeignKey("collection_zones.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    helpful_count = Column(Integer, default=0)

class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    waste_type = Column(Enum(WasteType), nullable=False)
    price_per_kg = Column(Float, nullable=False)
    min_kg = Column(Float, default=0)
    max_kg = Column(Float, nullable=True)
    available_kg = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    views = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    user = relationship("User", foreign_keys=[user_id])

class MarketplaceOrder(Base):
    __tablename__ = "marketplace_orders"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("marketplace_listings.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity_kg = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    status = Column(Enum("pending", "accepted", "completed", "cancelled", name="order_status"), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    listing = relationship("MarketplaceListing")
    buyer = relationship("User", foreign_keys=[buyer_id])
    seller = relationship("User", foreign_keys=[seller_id])