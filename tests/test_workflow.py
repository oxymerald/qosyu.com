"""Run only against an isolated test database; modifies test users and requests."""
import asyncio
import os
import unittest
import uuid

import httpx


@unittest.skipUnless(os.getenv("QOSYU_ISOLATED_TEST") == "1", "requires isolated test instance")
class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_pickup_lifecycle_permissions_and_concurrent_zones(self):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
            suffix = uuid.uuid4().hex[:10]
            headers = []
            for role, name in [("sme", "Shop"), ("recycler", "Recycler A"), ("recycler", "Recycler B")]:
                email = f"{role}-{len(headers)}-{suffix}@example.com"
                password = "LocalTest-2026!"
                response = await client.post("/auth/register", json={"email": email, "password": password, "company_name": name, "role": role})
                self.assertEqual(response.status_code, 201, response.text)
                response = await client.post("/auth/login", json={"email": email, "password": password})
                self.assertEqual(response.status_code, 200, response.text)
                headers.append({"Authorization": f"Bearer {response.json()['access_token']}"})
            sme, recycler, other = headers
            self.assertEqual((await client.post("/requests/create", headers=recycler, json={"waste_type": "plastic", "weight_kg": 5, "latitude": 47.1, "longitude": 51.88})).status_code, 403)
            ids = []
            for lat, lon in [(47.1167, 51.88), (47.1167, 51.904), (47.3, 52.1)]:
                r = await client.post("/requests/create", headers=sme, json={"waste_type": "cardboard", "weight_kg": 10, "latitude": lat, "longitude": lon})
                self.assertEqual(r.status_code, 201, r.text)
                ids.append(r.json()["id"])
            self.assertEqual(len((await client.get("/requests/my", headers=sme)).json()), 3)
            self.assertEqual((await client.get("/requests/my", headers=other)).json(), [])
            # Two workers may run together, but a request must never appear in two zones.
            a, b = await asyncio.gather(*[client.post("/clustering/generate-zones", headers=h) for h in [recycler, other]])
            self.assertIn(200, [a.status_code, b.status_code])
            self.assertTrue(all(r.status_code in [200, 409] for r in [a, b]), [a.text, b.text])
            zone_ids = [z for r in [a, b] if r.status_code == 200 for z in r.json()["zone_ids"]]
            seen = []
            selected_zone = None
            for zid in zone_ids:
                response = await client.get(f"/recycler/zones/{zid}/route", headers=recycler)
                self.assertEqual(response.status_code, 200, response.text)
                route = response.json()
                self.assertTrue(route["approximate"])
                self.assertEqual(route["source"], "heuristic")
                relevant = [s["request_id"] for s in route["stops"] if s["request_id"] in ids]
                seen.extend(relevant)
                if ids[0] in relevant:
                    selected_zone = zid
                    self.assertIn(ids[1], relevant)
            self.assertEqual(sorted(seen), sorted(ids))
            self.assertIsNotNone(selected_zone)
            url = f"/recycler/zones/{selected_zone}"
            self.assertEqual((await client.get(url + "/route?start_lat=47.12", headers=recycler)).status_code, 422)
            r = await client.get(url + "/route?start_lat=47.12&start_lon=51.9", headers=recycler)
            self.assertEqual(r.json()["start"], {"lat": 47.12, "lon": 51.9})
            self.assertEqual((await client.get(url + "/route", headers=sme)).status_code, 403)
            self.assertEqual((await client.delete(f"/requests/{ids[0]}", headers=sme)).status_code, 409)
            a, b = await asyncio.gather(client.post(url + "/assign", headers=recycler), client.post(url + "/assign", headers=other))
            self.assertEqual(sorted([a.status_code, b.status_code]), [200, 409])
            winner, loser = (recycler, other) if a.status_code == 200 else (other, recycler)
            self.assertEqual((await client.get(url + "/route", headers=loser)).status_code, 403)
            self.assertEqual((await client.post(url + "/complete", headers=loser)).status_code, 404)
            mine = (await client.get("/recycler/zones/my", headers=winner)).json()
            self.assertIn(selected_zone, [z["id"] for z in mine])
            self.assertEqual((await client.post(url + "/complete", headers=winner)).status_code, 200)
            self.assertEqual((await client.post(url + "/complete", headers=winner)).status_code, 409)
            mine = (await client.get("/recycler/zones/my", headers=winner)).json()
            self.assertNotIn(selected_zone, [z["id"] for z in mine])
            reqs = (await client.get("/requests/my", headers=sme)).json()
            self.assertEqual({r["status"] for r in reqs if r["id"] in ids[:2]}, {"collected"})
            self.assertEqual((await client.get("/ai/status")).json()["available"], False)


if __name__ == "__main__":
    unittest.main()
