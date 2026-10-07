import copy
import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from config import settings
from models import CollectionZone, RequestStatus, User, UserRole, WasteRequest, WasteType, ZoneStatus
from routers.ai import AssistantIn, ai_status
from services import ai_tools, gemini


class GeminiTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_key_does_not_call_provider(self):
        with patch.object(settings, "GEMINI_API_KEY", ""), patch.object(gemini, "_generate", new=AsyncMock()) as generate:
            with self.assertRaises(HTTPException) as caught:
                await gemini.assistant(AssistantIn(message="Покажи заявки"), None, None)
            self.assertEqual(caught.exception.status_code, 503)
            generate.assert_not_called()

    async def test_provider_status_never_exposes_key(self):
        with patch.object(settings, "GEMINI_API_KEY", "test-secret"), patch.object(settings, "AI_PROVIDER", "gemini"):
            status = await ai_status()
            self.assertTrue(status["available"])
            self.assertEqual(status["provider"], "gemini")
            self.assertNotIn("test-secret", json.dumps(status))

    async def test_rest_header_and_sanitized_errors(self):
        client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "OK"}]}}]})))
        with patch.object(settings, "GEMINI_API_KEY", "test-secret"):
            await gemini._generate(client, {"contents": []})
        args = client.post.call_args
        self.assertNotIn("test-secret", args.args[0])
        self.assertEqual(args.kwargs["headers"]["x-goog-api-key"], "test-secret")
        for status, expected in [(429, 429), (403, 503), (400, 503), (404, 503), (500, 502)]:
            client.post.return_value = httpx.Response(status, text="test-secret provider detail")
            with self.assertRaises(HTTPException) as caught:
                await gemini._generate(client, {})
            self.assertEqual(caught.exception.status_code, expected)
            self.assertNotIn("test-secret", caught.exception.detail)

    async def test_tool_result_and_thought_signature_are_preserved(self):
        model_turn = {"role": "model", "parts": [{"thoughtSignature": "opaque-signature", "functionCall": {"id": "call-1", "name": "show_requests", "args": {"waste_type": "cardboard"}}}]}
        captured = []
        async def generate(client, payload):
            captured.append(copy.deepcopy(payload))
            return model_turn if len(captured) == 1 else {"role": "model", "parts": [{"text": "Найдена заявка #42"}]}
        execute = AsyncMock(return_value=({"items": [{"id": 42}], "truncated": False}, {"type": "show_requests", "ids": [42]}))
        with patch.object(settings, "GEMINI_API_KEY", "test-secret"), patch.object(gemini, "_generate", side_effect=generate), patch.object(ai_tools, "execute", new=execute):
            result = await gemini.assistant(AssistantIn(message="Покажи картон"), None, SimpleNamespace(role=UserRole.SME))
        self.assertEqual(result["actions"], [{"type": "show_requests", "ids": [42]}])
        self.assertEqual(captured[1]["contents"][-2], model_turn)
        self.assertEqual(captured[1]["contents"][-1]["parts"][0]["functionResponse"]["id"], "call-1")
        self.assertNotIn("test-secret", json.dumps(captured))
        self.assertEqual([d["name"] for d in captured[0]["tools"][0]["functionDeclarations"]], ["show_requests"])

    async def test_excessive_tool_calls_are_not_executed(self):
        response = {"role": "model", "parts": [{"functionCall": {"name": "show_requests", "args": {}}}] * 6}
        with patch.object(settings, "GEMINI_API_KEY", "test-secret"), patch.object(gemini, "_generate", new=AsyncMock(return_value=response)), patch.object(ai_tools, "execute", new=AsyncMock()) as execute:
            result = await gemini.assistant(AssistantIn(message="Покажи всё"), None, SimpleNamespace(role=UserRole.SME))
        execute.assert_not_awaited()
        self.assertEqual(result["actions"], [])

    async def test_round_limit_and_model_tool_disable(self):
        snapshots = []
        async def generate(client, payload):
            snapshots.append(copy.deepcopy(payload))
            return {"role": "model", "parts": [{"functionCall": {"name": "show_requests", "args": {}}}]}
        with patch.object(settings, "GEMINI_API_KEY", "test-secret"), patch.object(gemini, "_generate", side_effect=generate), patch.object(ai_tools, "execute", new=AsyncMock(return_value=({"items": []}, None))) as execute:
            await gemini.assistant(AssistantIn(message="Ищи дальше"), None, SimpleNamespace(role=UserRole.SME))
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(execute.await_count, 2)
        self.assertEqual(snapshots[-1]["toolConfig"]["functionCallingConfig"]["mode"], "NONE")

    async def test_unknown_tool_cannot_mutate(self):
        result, action = await ai_tools.execute("complete_zone", {"zone_id": 1}, None, SimpleNamespace(role=UserRole.RECYCLER))
        self.assertIn("error", result)
        self.assertIsNone(action)

    async def test_sme_cannot_invoke_recycler_tools(self):
        for name, args in [("show_zones", {}), ("preview_route", {"zone_id": 1})]:
            result, action = await ai_tools.execute(name, args, None, SimpleNamespace(role=UserRole.SME))
            self.assertIn("error", result)
            self.assertIsNone(action)

    async def test_invalid_tool_arguments_are_rejected(self):
        for args in [{"zone_id": "DROP TABLE users"}, {"zone_id": True}, {"zone_id": 1, "user_id": 2}]:
            result, action = await ai_tools.execute("preview_route", args, None, SimpleNamespace(role=UserRole.RECYCLER))
            self.assertIn("error", result)
            self.assertIsNone(action)


@unittest.skipUnless(os.getenv("QOSYU_ISOLATED_TEST") == "1", "requires isolated database")
class ToolAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_scope_and_full_mocked_conversation(self):
        # A dedicated engine per test loop avoids sharing connections across unittest loops.
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine = create_async_engine(settings.DATABASE_URL)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                people = []
                for role in [UserRole.SME, UserRole.SME, UserRole.RECYCLER, UserRole.RECYCLER]:
                    user = User(email=f"ai-{uuid.uuid4().hex}@example.com", hashed_password="test-only-not-a-login", company_name="Test", role=role)
                    db.add(user)
                    people.append(user)
                await db.flush()
                owner, stranger, recycler, other_recycler = people
                requests = []
                for sme, status in [(owner, RequestStatus.PENDING), (stranger, RequestStatus.ASSIGNED), (owner, RequestStatus.ASSIGNED)]:
                    req = WasteRequest(sme_id=sme.id, waste_type=WasteType.CARDBOARD, weight_kg=10, latitude=47.11, longitude=51.88, location_geom="SRID=4326;POINT(51.88 47.11)", status=status)
                    db.add(req)
                    requests.append(req)
                await db.flush()
                zones = []
                for r, req in [(other_recycler, requests[1]), (recycler, requests[2])]:
                    zone = CollectionZone(centroid_lat=47.11, centroid_lon=51.88, radius_km=0, total_weight_kg=10, request_ids=[req.id], recycler_id=r.id, status=ZoneStatus.ASSIGNED)
                    db.add(zone)
                    zones.append(zone)
                await db.flush()
                for user, forbidden in [(owner, requests[1]), (stranger, requests[0]), (recycler, requests[1])]:
                    with self.assertRaises(HTTPException) as caught:
                        await ai_tools.map_items("requests", [forbidden.id], db, user)
                    self.assertEqual(caught.exception.status_code, 404)
                items = await ai_tools.map_items("requests", [requests[0].id, requests[2].id], db, recycler)
                self.assertEqual(len(items), 2)
                result, action = await ai_tools.execute("preview_route", {"zone_id": zones[0].id}, db, recycler)
                self.assertIn("error", result)
                self.assertIsNone(action)
                from routers.ai import MapStart
                with patch.object(settings, "OSRM_BASE_URL", ""):
                    result, action = await ai_tools.execute("preview_route", {"zone_id": zones[1].id}, db, recycler, MapStart(lat=47.12, lon=51.9))
                self.assertTrue(result["approximate"])
                self.assertEqual(action["start"], {"lat": 47.12, "lon": 51.9})
                self.assertNotIn("company", json.dumps(result))
                turns = [
                    {"role": "model", "parts": [{"functionCall": {"name": "show_requests", "args": {"waste_type": "cardboard"}}}]},
                    {"role": "model", "parts": [{"text": "Заявки найдены."}]},
                ]
                with patch.object(settings, "GEMINI_API_KEY", "test-secret"), patch.object(gemini, "_generate", new=AsyncMock(side_effect=turns)):
                    result = await gemini.assistant(AssistantIn(message="Покажи мои заявки на картон"), db, owner)
                self.assertEqual(set(result["actions"][0]["ids"]), {requests[0].id, requests[2].id})
                self.assertNotIn(requests[1].id, result["actions"][0]["ids"])
                self.assertEqual((await db.execute(select(CollectionZone.status).where(CollectionZone.id == zones[1].id))).scalar(), ZoneStatus.ASSIGNED)
            finally:
                await db.rollback()  # No test rows remain.
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
