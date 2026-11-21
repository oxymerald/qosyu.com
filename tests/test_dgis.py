"""2GIS contract and fallback tests; all provider responses are synthetic."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException

from config import settings
from routers import maps
from services import dgis, geo


class DgisTests(unittest.IsolatedAsyncioTestCase):
    points = [(47.11, 51.88), (47.12, 51.89), (47.13, 51.9), (47.11, 51.88)]

    def response(self):
        return {"status": "OK", "type": "result", "result": [{
            "waypoints": [{"original_point": {"lat": p[0], "lon": p[1]}} for p in self.points],
            "total_distance": 2400, "total_duration": 400,
            "maneuvers": [{"outcoming_path": {"geometry": [{
                "selection": "LINESTRING(51.88 47.11,51.89 47.12,51.9 47.13,51.88 47.11)"}]}}]}]}

    def test_route_order_units_and_geometry(self):
        route = dgis.parse_route(self.response(), self.points, [0, 1])
        self.assertEqual(route["source"], "2gis")
        self.assertEqual(route["duration_seconds"], 1120)
        self.assertEqual(route["distance_meters"], 2400)
        self.assertEqual(route["geometry"], list(map(list, self.points)))

    def test_rejects_incomplete_or_changed_waypoints(self):
        for change in (lambda r: r["waypoints"].pop(), lambda r: r["waypoints"][1]["original_point"].update(lat=47.5)):
            data = self.response()
            change(data["result"][0])
            with self.assertRaises(ValueError):
                dgis.parse_route(data, self.points, [0, 1])

    def test_rejects_bad_metrics_and_discontinuous_geometry(self):
        for metric in (-1, float("nan"), float("inf"), "400", True):
            data = self.response()
            data["result"][0]["total_distance"] = metric
            with self.assertRaises(ValueError):
                dgis.parse_route(data, self.points, [0, 1])
        data = self.response()
        data["result"][0]["maneuvers"][0]["outcoming_path"]["geometry"].append({"selection": "LINESTRING(52 48,53 49)"})
        with self.assertRaises(ValueError):
            dgis.parse_route(data, self.points, [0, 1])

    def test_rejects_bad_wkt(self):
        for value in (None, "POINT(51 47)", "LINESTRING(51 47)", "LINESTRING(nan 47,51 48)", "LINESTRING(51 91,51 48)"):
            with self.assertRaises(ValueError):
                dgis.linestring(value)

    def test_accepts_nearby_depot_road_access_but_rejects_remote_snap(self):
        data = self.response()
        data["result"][0]["waypoints"][0]["original_point"]["lat"] += .0002
        self.assertEqual(dgis.parse_route(data, self.points, [0, 1])["source"], "2gis")
        data["result"][0]["waypoints"][0]["original_point"]["lat"] += .1
        with self.assertRaises(ValueError):
            dgis.parse_route(data, self.points, [0, 1])

    async def test_intermediate_points_are_mandatory_not_alternative_destinations(self):
        dgis._route_cache.clear()
        with patch.object(dgis, "request", AsyncMock(return_value=httpx.Response(200, json=self.response()))) as request:
            await dgis.road_route(self.points[0], self.points[1:3], [0, 1])
        self.assertEqual([p["type"] for p in request.call_args.kwargs["json"]["points"]], ["stop", "pref", "pref", "stop"])

    async def test_too_many_stops_falls_back_before_api_call(self):
        with patch.object(dgis, "request", AsyncMock()) as request:
            with self.assertRaises(HTTPException):
                await dgis.road_route(self.points[0], [self.points[1]] * 9, list(range(9)))
        request.assert_not_awaited()

    async def test_cache_keeps_original_stop_mapping_and_returns_copy(self):
        dgis._route_cache.clear()
        mock = AsyncMock(return_value=httpx.Response(200, json=self.response()))
        with patch.object(settings, "DGIS_API_KEY", "unit-test-secret"), patch.object(dgis, "request", mock):
            first = await dgis.road_route(self.points[0], self.points[1:3], [0, 1])
            first["geometry"].clear()
            again = await dgis.road_route(self.points[0], self.points[1:3], [0, 1])
            self.assertEqual(len(again["geometry"]), 4)
            changed_input = await dgis.road_route(self.points[0], list(reversed(self.points[1:3])), [1, 0])
            self.assertEqual(changed_input["waypoint_order"], [1, 0])
            self.assertEqual(mock.await_count, 2)

    async def test_geocoder_filters_invalid_points_and_empty_results(self):
        data = {"meta": {"code": 200}, "result": {"items": [
            {"full_name": "Атырау, улица Абая, 1", "point": {"lat": 47.11, "lon": 51.88}},
            {"name": "invalid", "point": {"lat": 100, "lon": 51.88}}]}}
        with patch.object(dgis, "request", AsyncMock(return_value=httpx.Response(200, json=data))):
            found = await dgis.geocode("Атырау Абая 1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["lat"], 47.11)
        with patch.object(dgis, "request", AsyncMock(return_value=httpx.Response(200, json={"meta": {"code": 404}}))):
            self.assertEqual(await dgis.geocode("missing"), [])

    async def test_no_key_and_provider_errors_never_leak_secrets(self):
        with patch.object(settings, "DGIS_API_KEY", ""):
            with self.assertRaises(HTTPException) as error:
                await dgis.request("GET", "https://example.invalid")
            self.assertEqual(error.exception.status_code, 503)
        for status, expected in [(401, 503), (403, 503), (429, 429), (500, 502)]:
            with patch.object(settings, "DGIS_API_KEY", "unit-test-secret"), patch.object(dgis.httpx, "AsyncClient") as client:
                client.return_value.__aenter__.return_value.request = AsyncMock(return_value=httpx.Response(status, text="unit-test-secret"))
                with self.assertRaises(HTTPException) as error:
                    await dgis.request("GET", "https://example.invalid")
                self.assertEqual(error.exception.status_code, expected)
                self.assertNotIn("unit-test-secret", error.exception.detail)

    async def test_status_exposes_presence_only_and_tiles_validate_bounds(self):
        with patch.object(settings, "DGIS_API_KEY", "unit-test-secret"):
            self.assertEqual(await maps.status(), {"provider": "2gis", "geocoder": True})
            self.assertNotIn("unit-test-secret", json.dumps(await maps.status()))
        for coords in [(20, 0, 0), (1, 2, 0), (1, -1, 0)]:
            with self.assertRaises(HTTPException) as error:
                await maps.tile(*coords, _=None)
            self.assertEqual(error.exception.status_code, 422)

    async def test_unavailable_provider_falls_back_with_explicit_warning(self):
        with patch.object(settings, "DGIS_API_KEY", "unit-test-secret"), patch.object(dgis, "road_matrix", AsyncMock(side_effect=HTTPException(429, "quota"))), patch.object(dgis, "road_route", AsyncMock(side_effect=HTTPException(429, "quota"))), patch.object(geo, "osrm_trip", AsyncMock(return_value=None)):
            route = await geo.compute_route(self.points[0], self.points[1:3], "")
        self.assertEqual(route["source"], "heuristic")
        self.assertEqual(route["provider_warning"], "2gis_unavailable")

    async def test_background_opt_out_does_not_spend_provider_quota(self):
        with patch.object(settings, "DGIS_API_KEY", "unit-test-secret"), patch.object(dgis, "road_route", AsyncMock()) as route, patch.object(geo, "osrm_trip", AsyncMock(return_value=None)):
            await geo.compute_route(self.points[0], self.points[1:3], "", use_dgis=False)
        route.assert_not_awaited()
