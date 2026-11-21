import itertools
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from config import settings
from services import dgis, geo
from security import rate_limiter


class MatrixTests(unittest.IsolatedAsyncioTestCase):
    matrix = [[0, 2, 20, 9], [8, 0, 1, 20], [3, 15, 0, 1], [1, 2, 15, 0]]

    def response(self):
        return {"routes": [dict(source_id=i, target_id=j, duration=v, status="OK")
                           for i, row in enumerate(self.matrix) for j, v in enumerate(row)]}

    def test_directed_tour_matches_exhaustive_search(self):
        def cost(order):
            points = [0] + [i + 1 for i in order] + [0]
            return sum(self.matrix[a][b] for a, b in zip(points, points[1:]))
        order = geo.matrix_stop_order(self.matrix)
        self.assertEqual(sorted(order), [0, 1, 2])
        self.assertEqual(cost(order), min(cost(p) for p in itertools.permutations(range(3))))
        self.assertEqual(order, [0, 1, 2])

    def test_missing_unreachable_duplicate_and_invalid_pairs_rejected(self):
        for change in (lambda r: r.pop(1), lambda r: r[1].update(status="FAIL"),
                       lambda r: r.append(r[1]), lambda r: r[1].update(duration=float('nan')),
                       lambda r: r[1].update(source_id=True)):
            response = self.response()
            change(response['routes'])
            with self.assertRaises(ValueError):
                dgis.parse_matrix(response, 4)

    async def test_cache_and_budget_avoid_additional_provider_requests(self):
        dgis._matrix_cache.clear()
        args = ((47.1, 51.8), [(47.11, 51.81), (47.12, 51.82), (47.13, 51.83)])
        with patch.object(dgis, 'request', AsyncMock(return_value=httpx.Response(200, json=self.response()))) as request, patch.object(rate_limiter, 'hit', AsyncMock(return_value=True)) as budget:
            matrix = await dgis.road_matrix(*args)
            matrix[0][1] = 999
            self.assertEqual((await dgis.road_matrix(*args))[0][1], 2)
            self.assertEqual(request.await_count, 1)
            self.assertEqual(budget.await_count, 1)
        dgis._matrix_cache.clear()
        with patch.object(dgis, 'request', AsyncMock()) as request, patch.object(rate_limiter, 'hit', AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException):
                await dgis.road_matrix(*args)
            request.assert_not_awaited()

    async def test_route_uses_matrix_order_and_reports_fallback(self):
        stops = [(47.11, 51.81), (47.12, 51.82), (47.13, 51.83)]
        with patch.object(settings, 'DGIS_API_KEY', 'unit-test'), patch.object(dgis, 'road_matrix', AsyncMock(return_value=self.matrix)), patch.object(dgis, 'road_route', AsyncMock(return_value={'source':'2gis'})) as route:
            result = await geo.compute_route((47.1, 51.8), stops, '')
            self.assertEqual(route.call_args.args[2], [0, 1, 2])
            self.assertEqual(result['order_source'], '2gis_matrix')
        with patch.object(settings, 'DGIS_API_KEY', 'unit-test'), patch.object(dgis, 'road_matrix', AsyncMock(side_effect=HTTPException(403))), patch.object(dgis, 'road_route', AsyncMock(return_value={'source':'2gis'})):
            result = await geo.compute_route((47.1, 51.8), stops, '')
            self.assertEqual(result['order_source'], 'geographic')
