"""Гео-сервисы: кластеризация заявок и построение оптимального маршрута.

Маршрут строится в два уровня:
1. Локальная эвристика (ближайший сосед + 2-opt) — работает всегда, без внешних
   сервисов. Дистанции по хаверсину, время — по средней городской скорости.
2. OSRM (если доступен) — уточняет порядок, дистанцию, время и даёт геометрию
   по реальным дорогам.
"""

import math

import httpx
import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.ext.asyncio import AsyncSession

from models import CollectionZone, WasteRequest, ZoneStatus

EARTH_RADIUS_KM = 6371.0
CITY_SPEED_KMH = 32.0  # средняя скорость грузовика в городе
STOP_SERVICE_MIN = 6.0  # время на погрузку в каждой точке


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# ---------- Кластеризация ----------

def cluster_requests(requests: list[WasteRequest], eps_deg=0.018, min_samples=2):
    """Группирует близкие заявки (DBSCAN по координатам). ~0.018° ≈ 2 км."""
    if len(requests) < min_samples:
        return []
    coords = np.array([[r.latitude, r.longitude] for r in requests])
    clustering = DBSCAN(eps=eps_deg, min_samples=min_samples).fit(coords)
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
            radius_km=2.0,
            total_weight_kg=sum(r.weight_kg for r in group),
            request_ids=[r.id for r in group],
            status=ZoneStatus.OPEN,
            optimized_route=None,
        )
        db.add(zone)
        zones.append(zone)
    await db.commit()
    for zone in zones:
        await db.refresh(zone)
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
        if data.get("code") != "Ok" or not data.get("trips"):
            return None
        trip = data["trips"][0]
        # waypoints[k].waypoint_index — позиция k-й входной точки в объезде.
        # Индекс 0 — депо; для остановок вычитаем 1 и сортируем по позиции.
        stop_positions = [
            (wp.get("waypoint_index", 0), idx - 1)
            for idx, wp in enumerate(data.get("waypoints", []))
            if idx > 0
        ]
        order = [stop_idx for _, stop_idx in sorted(stop_positions)]
        # GeoJSON отдаёт [lon, lat] — переворачиваем для Leaflet
        geometry = [[lat, lon] for lon, lat in trip.get("geometry", {}).get("coordinates", [])]
        return {
            "source": "osrm",
            "waypoint_order": order,
            "distance_meters": round(trip.get("distance", 0)),
            "duration_seconds": round(trip.get("duration", 0) + STOP_SERVICE_MIN * 60 * len(stops)),
            "geometry": geometry,
        }
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def compute_route(
    depot: tuple[float, float], stops: list[tuple[float, float]], osrm_url: str
) -> dict:
    """OSRM, а при его недоступности — локальная эвристика. Всегда даёт маршрут."""
    route = await osrm_trip(depot, stops, osrm_url)
    if route is None:
        route = build_local_route(depot, stops)
    return route


async def optimize_route(
    zone: CollectionZone, requests: list[WasteRequest], osrm_url: str
) -> CollectionZone:
    """Сохраняет маршрут в zone.optimized_route (вызывается фоновой задачей)."""
    from config import settings

    depot = (settings.DEPOT_LAT, settings.DEPOT_LON)
    stops = [(r.latitude, r.longitude) for r in requests]
    route = await compute_route(depot, stops, osrm_url)
    route["request_order"] = [requests[i].id for i in route["waypoint_order"]]
    zone.optimized_route = route
    return zone
