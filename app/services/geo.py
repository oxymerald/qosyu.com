import httpx
import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.ext.asyncio import AsyncSession

from models import CollectionZone, WasteRequest, ZoneStatus


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


async def optimize_route(
    zone: CollectionZone, requests: list[WasteRequest], osrm_url: str
) -> CollectionZone:
    """Строит оптимальный маршрут через OSRM. При недоступности OSRM зона
    остаётся рабочей без маршрута."""
    depot = (47.1167, 51.8833)  # Атырау, пилотная зона
    waypoints = [depot] + [(r.latitude, r.longitude) for r in requests] + [depot]
    coords_str = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    url = (
        f"{osrm_url}/trip/v1/driving/{coords_str}"
        "?roundtrip=true&source=first&destination=last&overview=full"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            trip = data.get("trips", [{}])[0] if data.get("trips") else data.get("trip", {})
            waypoint_order = data.get("waypoints", [])
            zone.optimized_route = {
                "waypoint_order": [w.get("waypoint_index") for w in waypoint_order],
                "polyline": trip.get("geometry", ""),
                "distance_meters": trip.get("distance"),
                "duration_seconds": trip.get("duration"),
            }
    except httpx.HTTPError:
        pass
    return zone
