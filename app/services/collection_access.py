"""Database predicates shared by recycler screens and assistant tools."""
from sqlalchemy import and_, cast, func, or_
from sqlalchemy.dialects.postgresql import JSONB

from models import CollectionZone, UserRole, WasteRequest, ZoneStatus


def visible_zone_condition(user, *, include_completed=True):
    public_zone = and_(CollectionZone.status == ZoneStatus.OPEN, CollectionZone.recycler_id.is_(None))
    if user.role == UserRole.ADMIN:
        return CollectionZone.id.is_not(None)
    statuses = [ZoneStatus.ASSIGNED, ZoneStatus.IN_PROGRESS]
    if include_completed:
        statuses.append(ZoneStatus.COMPLETED)
    return or_(
        public_zone,
        and_(CollectionZone.recycler_id == user.id, CollectionZone.status.in_(statuses)),
    )


def zone_has_request():
    return cast(CollectionZone.request_ids, JSONB).contains(func.jsonb_build_array(WasteRequest.id))
