import numpy as np
from sklearn.cluster import DBSCAN
from geopy.distance import geodesic
from models import WasteRequest, CollectionZone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import httpx

def cluster_requests(requests: list[WasteRequest], eps_deg=0.018, min_samples=2):
    if len(requests) < min_samples:
        return []
    coords = np.array([[r.latitude, r.longitude] for r in requests])
    clustering = DBSCAN(eps=eps_deg, min_samples=min_samples).fit(coords)
    labels = clustering.labels_
    clusters = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(requests[idx])
    return list(clusters.values())

async def create_collection_zones(db: AsyncSession, requests: list[WasteRequest]):
    from models import CollectionZone, ZoneStatus
    zones = []
    request_groups = cluster_requests(requests)
    for group in request_groups:
        lat = sum(r.latitude for r in group) / len(group)
        lon = sum(r.longitude for r in group) / len(group)
        total_weight = sum(r.weight_kg for r in group)
        zone = CollectionZone(
            centroid_lat=lat,
            centroid_lon=lon,
            radius_km=2.0,
            total_weight_kg=total_weight,
            request_ids=[r.id for r in group],
            status=ZoneStatus.OPEN,
            optimized_route=None
        )
        db.add(zone)
        zones.append(zone)
    await db.commit()
    for zone in zones:
        await db.refresh(zone)
    return zones

async def optimize_route(zone: CollectionZone, osrm_url: str, google_api_key: str = None):
    depot = (43.2567, 76.9286)   # Almaty center example
    waypoints = [depot] + [(r.latitude, r.longitude) for r in getattr(zone, 'requests', [])] + [depot]
    coords_str = ";".join(f"{lon},{lat}" for lat,lon in waypoints)
    url = f"{osrm_url}/trip/v1/driving/{coords_str}?roundtrip=true&source=first&destination=last&overview=full"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            waypoint_order = data.get("trip", {}).get("waypoints", [])
            polyline = data.get("trip", {}).get("geometry", "")
            zone.optimized_route = {
                "waypoint_order": [w["waypoint_index"] for w in waypoint_order],
                "polyline": polyline,
                "distance_meters": data["trip"]["distance"],
                "duration_seconds": data["trip"]["duration"]
            }
    return zone