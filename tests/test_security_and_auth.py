"""Unit tests for auth session revocation, WS tickets, and streaming body limits."""
import time
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from auth import validate_password_strength
from config import settings
from database import get_db
from main import app
from models import ChatMessage, User
from security import rate_limiter
from services import ws_tickets


class SecurityAndAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.execute(text(f"ATTACH DATABASE ':memory:' AS {settings.DATABASE_SCHEMA}"))
            await conn.run_sync(User.__table__.create)
            await conn.run_sync(ChatMessage.__table__.create)

        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        rate_limiter._local.clear()
        ws_tickets._local.clear()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    def test_password_strength_rules(self):
        self.assertIsNotNone(validate_password_strength("short1"))
        self.assertIsNotNone(validate_password_strength("onlyletters"))
        self.assertIsNotNone(validate_password_strength("12345678"))
        self.assertIsNotNone(validate_password_strength("a1" * 40))
        self.assertIsNone(validate_password_strength("ValidPass1"))

    async def test_register_cannot_self_assign_admin_and_password_change_revokes_old_token(self):
        resp = await self.client.post(
            "/auth/register",
            json={
                "email": "admin-try@example.com",
                "password": "Password1",
                "company_name": "Evil Corp",
                "role": "admin",
            },
        )
        self.assertEqual(resp.status_code, 422)

        resp = await self.client.post(
            "/auth/register",
            json={
                "email": "cafe@example.com",
                "password": "Password1",
                "company_name": "Test Cafe",
                "role": "sme",
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)

        login = await self.client.post(
            "/auth/login", json={"email": "cafe@example.com", "password": "Password1"}
        )
        self.assertEqual(login.status_code, 200, login.text)
        old_token = login.json()["access_token"]
        self.assertEqual(
            (await self.client.get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})).status_code,
            200,
        )

        changed = await self.client.post(
            "/auth/change-password",
            headers={"Authorization": f"Bearer {old_token}"},
            json={"current_password": "Password1", "new_password": "NewPassword2"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        new_token = changed.json()["access_token"]
        self.assertNotEqual(old_token, new_token)

        # Старый токен обязан мгновенно протухнуть после смены пароля.
        self.assertEqual(
            (await self.client.get("/auth/me", headers={"Authorization": f"Bearer {old_token}"})).status_code,
            401,
        )
        self.assertEqual(
            (await self.client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})).status_code,
            200,
        )

    async def test_ws_ticket_is_one_time_receiver_bound_and_respects_roles(self):
        # Создаём два SME и одного переработчика
        tokens = {}
        ids = {}
        for role, email in [("sme", "s1@example.com"), ("sme", "s2@example.com"), ("recycler", "r1@example.com")]:
            reg = await self.client.post(
                "/auth/register",
                json={"email": email, "password": "Password1", "company_name": email, "role": role},
            )
            self.assertEqual(reg.status_code, 201, reg.text)
            ids[email] = reg.json()["id"]
            login = await self.client.post("/auth/login", json={"email": email, "password": "Password1"})
            tokens[email] = login.json()["access_token"]

        # SME не может открыть чат с другим SME
        forbidden = await self.client.post(
            "/chat/ws-ticket",
            headers={"Authorization": f"Bearer {tokens['s1@example.com']}"},
            json={"receiver_id": ids["s2@example.com"]},
        )
        self.assertEqual(forbidden.status_code, 403)

        # SME может получить тикет для диалога с переработчиком
        ok = await self.client.post(
            "/chat/ws-ticket",
            headers={"Authorization": f"Bearer {tokens['s1@example.com']}"},
            json={"receiver_id": ids["r1@example.com"]},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        ticket = ok.json()["ticket"]

        # Чужой receiver_id отклоняет тикет (и тикет при этом сгорает)
        self.assertIsNone(await ws_tickets.redeem(ticket, ids["s2@example.com"]))
        self.assertIsNone(await ws_tickets.redeem(ticket, ids["r1@example.com"]))

        # Свежий тикет срабатывает ровно один раз
        fresh = await ws_tickets.issue(ids["s1@example.com"], ids["r1@example.com"])
        self.assertEqual(await ws_tickets.redeem(fresh, ids["r1@example.com"]), ids["s1@example.com"])
        self.assertIsNone(await ws_tickets.redeem(fresh, ids["r1@example.com"]))

        # Просроченный тикет не принимается
        expired = await ws_tickets.issue(ids["s1@example.com"], ids["r1@example.com"])
        uid, rid, _ = ws_tickets._local[expired]
        ws_tickets._local[expired] = (uid, rid, time.monotonic() - 1)
        self.assertIsNone(await ws_tickets.redeem(expired, ids["r1@example.com"]))

    async def test_body_size_limit_blocks_content_length_and_chunked_streams(self):
        with patch.object(settings, "MAX_BODY_SIZE", 64):
            # 1. Превышение по Content-Length
            resp = await self.client.post("/auth/login", content=b"x" * 100)
            self.assertEqual(resp.status_code, 413)

            # 2. Превышение через потоковую отправку без Content-Length
            async def chunks():
                yield b'{"email":"'
                yield b"a" * 80
                yield b'@example.com","password":"x"}'

            streamed = await self.client.post(
                "/auth/login",
                content=chunks(),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(streamed.status_code, 413)


if __name__ == "__main__":
    unittest.main()
