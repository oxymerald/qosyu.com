"""Read-only AI tools. Authorization is enforced here, never by the model."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select

from models import CollectionZone, RequestStatus, UserRole, WasteRequest, WasteType, ZoneStatus


class RequestFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    waste_type: WasteType | None = None
    status: RequestStatus | None = None


class ZoneFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field(default="open", pattern="^(open|mine)$")


class RouteFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zone_id: int = Field(gt=0, strict=True)


def declarations(role):
    tools = [{"name": "show_requests", "description": "Найти доступные заявки и добавить кнопку показа на карте. Максимум 50; при усечении уточни фильтр.",
              "parameters": {"type": "OBJECT", "properties": {
                  "waste_type": {"type": "STRING", "enum": [w.value for w in WasteType]},
                  "status": {"type": "STRING", "enum": [s.value for s in RequestStatus]}}}}]
    if role in (UserRole.RECYCLER, UserRole.ADMIN):
        tools += [
            {"name": "show_zones", "description": "Найти открытые зоны (open) или зоны в работе пользователя (mine), до 50. Добавить кнопку на карту.",
             "parameters": {"type": "OBJECT", "properties": {"scope": {"type": "STRING", "enum": ["open", "mine"]}}}},
            {"name": "preview_route", "description": "Рассчитать объезд зоны и добавить кнопку просмотра. Для начала используется выбранная на карте база или база по умолчанию. Зона не назначается.",
             "parameters": {"type": "OBJECT", "properties": {"zone_id": {"type": "INTEGER"}}, "required": ["zone_id"]}},
        ]
    return tools


async def visible_requests(db, user):
    query = select(WasteRequest)
    if user.role == UserRole.SME:
        return query.where(WasteRequest.sme_id == user.id)
    if user.role == UserRole.RECYCLER:
        zones = (await db.execute(select(CollectionZone.request_ids).where(CollectionZone.recycler_id == user.id))).scalars().all()
        own_ids = {rid for ids in zones for rid in (ids or [])}
        return query.where(or_(
            WasteRequest.status.in_([RequestStatus.PENDING, RequestStatus.CLUSTERED]),
            WasteRequest.id.in_(own_ids),
        ))
    if user.role == UserRole.ADMIN:
        return query
    raise HTTPException(403, "Недостаточно прав")


def visible_zones(user):
    query = select(CollectionZone)
    if user.role == UserRole.RECYCLER:
        return query.where(or_(CollectionZone.status == ZoneStatus.OPEN, CollectionZone.recycler_id == user.id))
    if user.role == UserRole.ADMIN:
        return query
    raise HTTPException(403, "Зоны доступны переработчику")


def request_data(r):
    return {"id": r.id, "latitude": r.latitude, "longitude": r.longitude,
            "waste_type": r.waste_type.value, "weight_kg": r.weight_kg, "status": r.status.value}


def zone_data(z):
    return {"id": z.id, "centroid_lat": z.centroid_lat, "centroid_lon": z.centroid_lon,
            "radius_km": z.radius_km, "total_weight_kg": z.total_weight_kg,
            "request_count": len(z.request_ids or []), "status": z.status.value}


async def map_items(kind, ids, db, user):
    if kind == "requests":
        query = (await visible_requests(db, user)).where(WasteRequest.id.in_(ids))
        serializer = request_data
    else:
        query = visible_zones(user).where(CollectionZone.id.in_(ids))
        serializer = zone_data
    items = (await db.execute(query)).scalars().all()
    if len(items) != len(set(ids)):
        raise HTTPException(404, "Часть выбранных объектов больше недоступна. Повторите поиск.")
    return [serializer(item) for item in items]


async def execute(name, args, db, user, map_start=None):
    """Return model data and optional server-built UI action; never mutate data."""
    try:
        if not isinstance(args, dict):
            raise ValueError("Ожидался объект аргументов")
        if name == "show_requests":
            filters = RequestFilter.model_validate(args)
            query = await visible_requests(db, user)
            if filters.waste_type is not None:
                query = query.where(WasteRequest.waste_type == filters.waste_type)
            if filters.status is not None:
                query = query.where(WasteRequest.status == filters.status)
            items = (await db.execute(query.order_by(WasteRequest.id.desc()).limit(51))).scalars().all()
            selected = items[:50]
            return {"items": [request_data(r) for r in selected], "truncated": len(items) > 50}, (
                {"type": "show_requests", "ids": [r.id for r in selected]} if selected else None)
        if name == "show_zones":
            filters = ZoneFilter.model_validate(args)
            query = visible_zones(user)
            if filters.scope == "open":
                query = query.where(CollectionZone.status == ZoneStatus.OPEN)
            else:
                query = query.where(CollectionZone.recycler_id == user.id,
                                    CollectionZone.status.in_([ZoneStatus.ASSIGNED, ZoneStatus.IN_PROGRESS]))
            items = (await db.execute(query.order_by(CollectionZone.id.desc()).limit(51))).scalars().all()
            selected = items[:50]
            return {"items": [zone_data(z) for z in selected], "truncated": len(items) > 50}, (
                {"type": "show_zones", "ids": [z.id for z in selected]} if selected else None)
        if name == "preview_route":
            if user.role not in (UserRole.RECYCLER, UserRole.ADMIN):
                raise HTTPException(403, "Маршрут доступен переработчику")
            params = RouteFilter.model_validate(args)
            from routers.recycler import zone_route
            route = await zone_route(params.zone_id,
                                     start_lat=map_start.lat if map_start else None,
                                     start_lon=map_start.lon if map_start else None,
                                     db=db, current_user=user)
            # No business names or full road geometry are sent to the AI provider.
            summary = {k: route[k] for k in ["zone_id", "source", "approximate", "distance_km", "duration_min", "total_weight_kg", "start"]}
            summary["request_ids"] = [stop["request_id"] for stop in route["stops"]]
            summary["service_minutes_per_stop"] = route["service_minutes_per_stop"]
            return summary, {"type": "show_route", "zone_id": params.zone_id, "start": route["start"]}
        return {"error": "Такого инструмента нет. Доступны только поиск и просмотр."}, None
    except (ValidationError, ValueError):
        return {"error": "Некорректные параметры инструмента. Проверьте тип, статус или номер зоны."}, None
    except HTTPException as exc:
        return {"error": exc.detail}, None
