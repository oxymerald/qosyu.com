"""2GIS adapters. Keys stay server-side, provider URLs must never be logged."""
import hashlib
import copy
import logging
import math
import re
import time
from collections import OrderedDict

import httpx
from fastapi import HTTPException

from config import settings

# httpx logs full URLs at INFO; 2GIS authenticates using a query parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
_route_cache = OrderedDict()
_matrix_cache = OrderedDict()


def parse_matrix(data, count):
    matrix = [[None] * count for _ in range(count)]
    for route in data["routes"]:
        i, j = route["source_id"], route["target_id"]
        value = route["duration"]
        if type(i) is not int or type(j) is not int or not (0 <= i < count and 0 <= j < count):
            raise ValueError("Invalid matrix indices")
        if matrix[i][j] is not None or route["status"] != "OK":
            raise ValueError("Duplicate or unreachable pair")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid duration")
        matrix[i][j] = value
    for i in range(count):
        matrix[i][i] = 0  # Some providers omit self-to-self pairs.
    if any(v is None for row in matrix for v in row):
        raise ValueError("Incomplete matrix")
    return matrix


async def road_matrix(depot, stops):
    """Bounded and cached directed travel-time matrix; no quota use in background."""
    if not settings.DGIS_MATRIX_ENABLED or not 2 <= len(stops) <= 8:
        raise HTTPException(422, "Матрица доступна для 2–8 остановок")
    points = [depot] + stops
    key = (hashlib.sha256(settings.DGIS_API_KEY.encode()).hexdigest(), tuple(map(tuple, points)))
    cached = _matrix_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        if cached[1] is None:
            raise HTTPException(503, "Матрица временно недоступна")
        return copy.deepcopy(cached[1])
    from security import rate_limiter
    if not await rate_limiter.hit("dgis-matrix-budget", max(0, settings.DGIS_MATRIX_DAILY_REQUESTS), 86400):
        raise HTTPException(429, "Дневной лимит расчётов матрицы исчерпан")
    # Cache failed requests too so repeated previews don't burn quota.
    _matrix_cache[key] = (time.monotonic(), None)
    _matrix_cache.move_to_end(key)
    while len(_matrix_cache) > 64:
        _matrix_cache.popitem(last=False)
    response = await request("POST", "https://routing.api.2gis.com/get_dist_matrix", params={"version": "2.0"}, json={
        "points": [{"lat": lat, "lon": lon} for lat, lon in points],
        "sources": list(range(len(points))), "targets": list(range(len(points)))})
    try:
        matrix = parse_matrix(response.json(), len(points))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise HTTPException(502, "2ГИС не вернул полную матрицу дорог") from None
    _matrix_cache[key] = (time.monotonic(), matrix)
    return copy.deepcopy(matrix)


async def request(method, url, **kwargs):
    if not settings.DGIS_API_KEY:
        raise HTTPException(503, "Ключ 2ГИС ещё не добавлен на сервере")
    params = dict(kwargs.pop("params", {}), key=settings.DGIS_API_KEY)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, url, params=params, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(502, "Нет связи с 2ГИС") from None
    if response.status_code in (401, 403):
        raise HTTPException(503, "2ГИС: проверьте ключ и доступ к нужному сервису")
    if response.status_code == 429:
        raise HTTPException(429, "Достигнут лимит 2ГИС. Проверьте квоту в кабинете.")
    if response.status_code != 200:
        raise HTTPException(502, "2ГИС не смог обработать запрос")
    return response


def valid_point(lat, lon):
    return (type(lat) in (int, float) and type(lon) in (int, float)
            and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180)


async def geocode(query):
    response = await request("GET", "https://catalog.api.2gis.com/3.0/items/geocode", params={
        "q": query, "fields": "items.point", "page_size": 5, "locale": "ru_KZ"})
    try:
        data = response.json()
        code = data.get("meta", {}).get("code")
        if code == 404:
            return []
        if code != 200:
            raise ValueError()
        found = []
        for item in data.get("result", {}).get("items", []):
            point = item.get("point", {})
            lat, lon = point.get("lat"), point.get("lon")
            if valid_point(lat, lon):
                found.append({"name": str(item.get("full_name") or item.get("name") or query)[:300], "lat": lat, "lon": lon})
        return found[:5]
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(502, "Не удалось прочитать адреса 2ГИС. Проверьте доступ к Geocoder API.") from None


def linestring(value):
    if not isinstance(value, str) or not re.fullmatch(r"LINESTRING\s*\([^()]+\)", value):
        raise ValueError("Invalid route geometry")
    points = []
    for pair in value[value.index("(") + 1:-1].split(","):
        lon, lat = map(float, pair.split())
        if not valid_point(lat, lon):
            raise ValueError("Invalid route coordinates")
        points.append([lat, lon])
    if len(points) < 2:
        raise ValueError("Empty route geometry")
    return points


def parse_route(data, points, order):
    if data.get("status") != "OK" or data.get("type") != "result":
        raise ValueError("No complete route")
    result = data["result"][0]
    waypoints = result["waypoints"]
    if len(waypoints) != len(points):
        raise ValueError("Missing waypoints")
    from services.geo import haversine_km
    for index, (returned, original) in enumerate(zip(waypoints, points)):
        p = returned["original_point"]
        if not valid_point(p["lat"], p["lon"]):
            raise ValueError("Changed waypoints")
        if index in (0, len(points) - 1):
            # 2GIS returns the road access point for endpoints, even in original_point.
            # Reject remote snapping instead of pretending the road reaches the depot.
            if haversine_km((p["lat"], p["lon"]), original) > .5:
                raise ValueError("Depot too far from road")
        elif abs(p["lat"] - original[0]) > .0001 or abs(p["lon"] - original[1]) > .0001:
            raise ValueError("Changed waypoints")
    distance, duration = result["total_distance"], result["total_duration"]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (distance, duration)):
        raise ValueError("Invalid metrics")
    geometry = []
    for maneuver in result["maneuvers"]:
        for segment in maneuver.get("outcoming_path", {}).get("geometry", []):
            part = linestring(segment["selection"])
            # A gap must not be silently drawn as a road segment.
            if geometry and (abs(geometry[-1][0] - part[0][0]) > .0001 or abs(geometry[-1][1] - part[0][1]) > .0001):
                raise ValueError("Discontinuous geometry")
            geometry.extend(part if not geometry else part[1:])
    if len(geometry) < 2:
        raise ValueError("No road geometry")
    return {"source": "2gis", "waypoint_order": order, "distance_meters": round(distance),
            "duration_seconds": round(duration + 360 * len(order)), "geometry": geometry}


async def road_route(depot, stops, order):
    # Routing API supports at most eight intermediate points. Preserve all stops
    # via the existing fallback instead of sending a truncated route.
    if len(order) > 8:
        raise HTTPException(422, "2ГИС: для этого маршрута больше 8 промежуточных точек")
    points = [depot] + [stops[i] for i in order] + [depot]
    key = (hashlib.sha256(settings.DGIS_API_KEY.encode()).hexdigest(), tuple(map(tuple, points)), tuple(order))
    cached = _route_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return copy.deepcopy(cached[1])
    response = await request("POST", "https://routing.api.2gis.com/routing/7.0.0/global", json={
        "points": [{"type": "stop" if i in (0, len(points) - 1) else "pref", "lat": lat, "lon": lon}
                   for i, (lat, lon) in enumerate(points)],
        "transport": "driving", "route_mode": "fastest", "traffic_mode": "jam", "locale": "ru", "alternative": 0,
        "output": "detailed"})
    try:
        route = parse_route(response.json(), points, order)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise HTTPException(502, "2ГИС не вернул полный дорожный маршрут") from None
    _route_cache[key] = (time.monotonic(), route)
    _route_cache.move_to_end(key)
    while len(_route_cache) > 64:
        _route_cache.popitem(last=False)
    return copy.deepcopy(route)
