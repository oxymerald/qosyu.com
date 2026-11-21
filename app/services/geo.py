"""Гео-сервисы: кластеризация заявок и построение оптимального маршрута.

Маршрут строится в два уровня:
1. Локальная эвристика (ближайший сосед + 2-opt) — работает всегда, без внешних
   сервисов. Дистанции по хаверсину, время — по средней городской скорости.
2. OSRM (если доступен) — уточняет порядок, дистанцию, время и даёт геометрию
   по реальным дорогам.
"""

import logging
import math

import httpx
import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CollectionZone, WasteRequest, ZoneStatus

logger = logging.getLogger("qosyu.geo")

EARTH_RADIUS_KM = 6371.0
CITY_SPEED_KMH = 32.0  # средняя скорость грузовика в городе
STOP_SERVICE_MIN = 6.0  # время на погрузку в каждой точке


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, h))))


# ---------- Кластеризация ----------

def cluster_requests(requests: list[WasteRequest], eps_km=2.0, min_samples=1):
    """DBSCAN по расстоянию на сфере; одиночная заявка тоже образует зону.

    eps_km — расстояние между соседями, не максимальный радиус всей зоны.
    """
    if len(requests) < min_samples:
        return []
    coords = np.radians([[r.latitude, r.longitude] for r in requests])
    clustering = DBSCAN(
        eps=eps_km / EARTH_RADIUS_KM, min_samples=min_samples, metric="haversine"
    ).fit(coords)
    clusters: dict[int, list[WasteRequest]] = {}
    for idx, label in enumerate(clustering.labels_):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(requests[idx])
    return list(clusters.values())


async def create_collection_zones(db: AsyncSession, requests: list[WasteRequest]):
    zones = []
    for group in cluster_requests(requests):
        lat = sum(r.latitude for r in group) / len(group)
        lon = sum(r.longitude for r in group) / len(group)
        zone = CollectionZone(
            centroid_lat=lat,
            centroid_lon=lon,
            radius_km=max(haversine_km((lat, lon), (r.latitude, r.longitude)) for r in group),
            total_weight_kg=sum(r.weight_kg for r in group),
            request_ids=[r.id for r in group],
            status=ZoneStatus.OPEN,
            optimized_route=None,
        )
        db.add(zone)
        zones.append(zone)
    # Зоны и статусы заявок сохраняются одной транзакцией у вызывающего кода.
    await db.flush()
    return zones


# ---------- Локальная TSP-эвристика ----------

def _nearest_neighbor_order(depot: tuple[float, float], stops: list[tuple[float, float]]) -> list[int]:
    remaining = list(range(len(stops)))
    order: list[int] = []
    current = depot
    while remaining:
        nearest = min(remaining, key=lambda i: haversine_km(current, stops[i]))
        order.append(nearest)
        current = stops[nearest]
        remaining.remove(nearest)
    return order


def _route_length(depot: tuple[float, float], stops: list[tuple[float, float]], order: list[int]) -> float:
    total = 0.0
    current = depot
    for i in order:
        total += haversine_km(current, stops[i])
        current = stops[i]
    return total + haversine_km(current, depot)


def _two_opt(depot: tuple[float, float], stops: list[tuple[float, float]], order: list[int]) -> list[int]:
    """Классическое 2-opt улучшение: разворачиваем отрезки, пока есть выигрыш."""
    best = order[:]
    best_len = _route_length(depot, stops, best)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                cand_len = _route_length(depot, stops, candidate)
                if cand_len < best_len - 1e-9:
                    best, best_len = candidate, cand_len
                    improved = True
    return best


def build_local_route(depot: tuple[float, float], stops: list[tuple[float, float]]) -> dict:
    """Маршрут без внешних сервисов: порядок, дистанция, оценка времени, геометрия."""
    if not stops:
        return {
            "source": "heuristic",
            "waypoint_order": [],
            "distance_meters": 0,
            "duration_seconds": 0,
            "geometry": [list(depot), list(depot)],
        }
    order = _two_opt(depot, stops, _nearest_neighbor_order(depot, stops))
    distance_km = _route_length(depot, stops, order)
    duration_min = (distance_km / CITY_SPEED_KMH) * 60 + STOP_SERVICE_MIN * len(stops)
    geometry = [list(depot)] + [list(stops[i]) for i in order] + [list(depot)]
    return {
        "source": "heuristic",
        "waypoint_order": order,
        "distance_meters": round(distance_km * 1000),
        "duration_seconds": round(duration_min * 60),
        "geometry": geometry,
    }


# ---------- OSRM ----------

def matrix_stop_order(matrix):
    """Exact small directed tour by dynamic programming; depot has index zero."""
    count = len(matrix) - 1
    if not 1 <= count <= 8:
        raise ValueError("Expected 1–8 stops")
    paths = {(1 << i, i): (matrix[0][i + 1], [i]) for i in range(count)}
    for mask in range(1, 1 << count):
        for last in range(count):
            entry = paths.get((mask, last))
            if entry is None:
                continue
            cost, order = entry
            for nxt in range(count):
                if mask & (1 << nxt):
                    continue
                key = (mask | (1 << nxt), nxt)
                candidate = (cost + matrix[last + 1][nxt + 1], order + [nxt])
                if key not in paths or candidate[0] < paths[key][0]:
                    paths[key] = candidate
    complete = (1 << count) - 1
    return min((paths[(complete, last)][0] + matrix[last + 1][0], paths[(complete, last)][1])
               for last in range(count))[1]

async def osrm_trip(
    depot: tuple[float, float], stops: list[tuple[float, float]], osrm_url: str
) -> dict | None:
    """Запрашивает оптимальный объезд у OSRM. None — если сервис недоступен."""
    if not osrm_url or not stops:
        return None
    waypoints = [depot] + stops
    coords_str = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    url = (
        f"{osrm_url.rstrip('/')}/trip/v1/driving/{coords_str}"
        "?roundtrip=true&source=first&overview=full&geometries=geojson"
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or data.get("code") != "Ok":
            return None
        trips, points = data.get("trips"), data.get("waypoints")
        if not isinstance(trips, list) or len(trips) != 1:
            return None
        if not isinstance(points, list) or len(points) != len(waypoints):
            return None
        if any(not isinstance(wp, dict) or wp.get("trips_index") != 0 for wp in points):
            return None
        indices = [wp.get("waypoint_index") for wp in points]
        if any(type(i) is not int for i in indices):
            return None
        if sorted(indices) != list(range(len(waypoints))) or indices[0] != 0:
            return None
        trip = data["trips"][0]
        if not isinstance(trip, dict):
            return None
        distance, duration = trip.get("distance"), trip.get("duration")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (distance, duration)):
            return None
        shape = trip.get("geometry")
        if not isinstance(shape, dict) or shape.get("type") != "LineString":
            return None
        coordinates = shape.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return None
        for point in coordinates:
            if not isinstance(point, list) or len(point) != 2:
                return None
            lon, lat = point
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                return None
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                return None
        # waypoints[k].waypoint_index — позиция k-й входной точки в объезде.
        # Индекс 0 — депо; для остановок вычитаем 1 и сортируем по позиции.
        stop_positions = [
            (wp.get("waypoint_index", 0), idx - 1)
            for idx, wp in enumerate(points)
            if idx > 0
        ]
        order = [stop_idx for _, stop_idx in sorted(stop_positions)]
        # GeoJSON отдаёт [lon, lat] — переворачиваем для Leaflet
        geometry = [[lat, lon] for lon, lat in coordinates]
        return {
            "source": "osrm",
            "waypoint_order": order,
            "distance_meters": round(distance),
            "duration_seconds": round(duration + STOP_SERVICE_MIN * 60 * len(stops)),
            "geometry": geometry,
        }
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def compute_route(
    depot: tuple[float, float], stops: list[tuple[float, float]], osrm_url: str, *, use_dgis=True
) -> dict:
    """2ГИС при наличии ключа, затем OSRM, затем схема прямых отрезков."""
    from config import settings
    from fastapi import HTTPException
    warning = None
    if use_dgis and settings.DGIS_API_KEY and stops:
        from services.dgis import road_matrix, road_route
        order = _two_opt(depot, stops, _nearest_neighbor_order(depot, stops))
        order_source = "geographic"
        if 2 <= len(stops) <= 8:
            try:
                order = matrix_stop_order(await road_matrix(depot, stops))
                order_source = "2gis_matrix"
            except HTTPException:
                pass
        try:
            route = await road_route(depot, stops, order)
            route["order_source"] = order_source if len(stops) > 1 else "single_stop"
            return route
        except HTTPException:
            warning = "2gis_unavailable"
    route = await osrm_trip(depot, stops, osrm_url)
    if route is None:
        route = build_local_route(depot, stops)
    if warning:
        route["provider_warning"] = warning
    return route


async def optimize_route(
    zone: CollectionZone, requests: list[WasteRequest], osrm_url: str
) -> CollectionZone:
    """Сохраняет маршрут в zone.optimized_route (вызывается фоновой задачей)."""
    from config import settings

    depot = (settings.DEPOT_LAT, settings.DEPOT_LON)
    stops = [(r.latitude, r.longitude) for r in requests]
    # Background work must not consume the demo's 2GIS quota.
    route = await compute_route(depot, stops, osrm_url, use_dgis=False)
    route["request_order"] = [requests[i].id for i in route["waypoint_order"]]
    zone.optimized_route = route
    return zone


async def compute_route_for_zone(zone_id: int) -> None:
    """Фоново пересчитывает и сохраняет маршрут зоны без расхода квоты 2ГИС."""
    from config import settings
    from database import async_session_maker

    try:
        async with async_session_maker() as db:
            zone = (
                await db.execute(select(CollectionZone).where(CollectionZone.id == zone_id))
            ).scalar_one_or_none()
            if zone is None:
                return
            reqs = (
                await db.execute(
                    select(WasteRequest).where(WasteRequest.id.in_(zone.request_ids or []))
                )
            ).scalars().all()
            await optimize_route(zone, reqs, settings.OSRM_BASE_URL)
            await db.commit()
    except Exception:
        # Маршрут можно построить и на лету через GET /recycler/zones/{id}/route.
        logger.warning("Фоновый расчёт маршрута для зоны #%s не удался", zone_id, exc_info=True)
