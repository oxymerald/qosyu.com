"""Regression tests; no external services or production data are used."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from services.geo import cluster_requests, create_collection_zones, compute_route, haversine_km, osrm_trip


def request(i, lat, lon):
    return SimpleNamespace(id=i, latitude=lat, longitude=lon, weight_kg=10)


class ClusteringTests(unittest.IsolatedAsyncioTestCase):
    def test_distance_is_km_at_atyrau_latitude(self):
        # 0.024 degrees of longitude is ~1.8 km here, not 2.7 km.
        points = [request(1, 47.1167, 51.88), request(2, 47.1167, 51.904)]
        self.assertLess(haversine_km((47.1167, 51.88), (47.1167, 51.904)), 2)
        self.assertEqual(len(cluster_requests(points)), 1)

    def test_separate_points_and_single_request_survive(self):
        points = [request(1, 47.1, 51.88), request(2, 47.2, 51.88)]
        self.assertEqual(len(cluster_requests(points)), 2)
        self.assertEqual(cluster_requests(points[:1]), [points[:1]])
        self.assertEqual(cluster_requests([]), [])

    async def test_radius_covers_chain_and_helper_does_not_commit(self):
        points = [request(i, 47.1 + i * .015, 51.88) for i in range(5)]
        db = SimpleNamespace(add=lambda zone: None, flush=AsyncMock(), commit=AsyncMock())
        zones = await create_collection_zones(db, points)
        self.assertEqual(len(zones), 1)
        self.assertGreater(zones[0].radius_km, 3)
        self.assertEqual(set(zones[0].request_ids), set(range(5)))
        db.commit.assert_not_awaited()
        db.flush.assert_awaited_once()


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    depot = (47.11, 51.88)
    stops = [(47.12, 51.89), (47.13, 51.9)]

    def valid(self):
        return {
            "code": "Ok",
            "waypoints": [{"trips_index": 0, "waypoint_index": i} for i in [0, 2, 1]],
            "trips": [{"distance": 1234, "duration": 300,
                       "geometry": {"type": "LineString", "coordinates": [[51.88, 47.11], [51.9, 47.13], [51.89, 47.12], [51.88, 47.11]]}}],
        }

    async def mocked(self, payload):
        with patch("services.geo.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.get = AsyncMock(return_value=httpx.Response(200, json=payload))
            return await osrm_trip(self.depot, self.stops, "https://routing.invalid")

    async def test_valid_road_route_order_units_and_geometry(self):
        route = await self.mocked(self.valid())
        self.assertEqual(route["waypoint_order"], [1, 0])
        self.assertEqual(route["duration_seconds"], 1020)
        self.assertEqual(route["geometry"][0], list(self.depot))
        self.assertEqual(route["source"], "osrm")

    async def test_rejects_split_trips(self):
        data = self.valid()
        data["trips"].append(copy.deepcopy(data["trips"][0]))
        self.assertIsNone(await self.mocked(data))

    async def test_rejects_missing_or_duplicate_waypoints(self):
        data = self.valid()
        data["waypoints"].pop()
        self.assertIsNone(await self.mocked(data))
        data = self.valid()
        data["waypoints"][1]["waypoint_index"] = 1
        self.assertIsNone(await self.mocked(data))

    async def test_rejects_other_trip_and_wrong_depot(self):
        data = self.valid()
        data["waypoints"][1]["trips_index"] = 1
        self.assertIsNone(await self.mocked(data))
        data = self.valid()
        data["waypoints"][0]["waypoint_index"], data["waypoints"][1]["waypoint_index"] = 2, 0
        self.assertIsNone(await self.mocked(data))

    async def test_rejects_invalid_geometry_and_distances(self):
        for value in [-1, None, "100"]:
            data = self.valid()
            data["trips"][0]["distance"] = value
            self.assertIsNone(await self.mocked(data))
        for point in [[181, 47], [51, 91], [None, 47], [51], "x"]:
            data = self.valid()
            data["trips"][0]["geometry"]["coordinates"][0] = point
            self.assertIsNone(await self.mocked(data))

    async def test_unavailable_service_falls_back_without_losing_stops(self):
        with patch("services.geo.osrm_trip", new=AsyncMock(return_value=None)):
            route = await compute_route(self.depot, self.stops, "")
        self.assertEqual(route["source"], "heuristic")
        self.assertEqual(sorted(route["waypoint_order"]), [0, 1])
        self.assertEqual(route["geometry"][0], route["geometry"][-1])
        self.assertGreater(route["distance_meters"], 0)

    async def test_network_error_is_handled(self):
        with patch("services.geo.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=httpx.ConnectError("offline"))
            self.assertIsNone(await osrm_trip(self.depot, self.stops, "https://routing.invalid"))


if __name__ == "__main__":
    unittest.main()
