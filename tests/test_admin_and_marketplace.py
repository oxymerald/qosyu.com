"""Unit tests for admin pilot intake visibility, search escaping, and marketplace orders."""
import unittest

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from auth import create_access_token, get_password_hash
from config import settings
from database import get_db
from main import app
from models import MarketplaceListing, MarketplaceOrder, PilotApplication, User, UserRole
from security import rate_limiter


class AdminAndMarketplaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.execute(text(f"ATTACH DATABASE ':memory:' AS {settings.DATABASE_SCHEMA}"))
            for model in (User, PilotApplication, MarketplaceListing, MarketplaceOrder):
                await conn.run_sync(model.__table__.create)

        async def isolated_db():
            async with AsyncSession(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        rate_limiter._local.clear()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )

        async with AsyncSession(self.engine) as db:
            self.admin = User(
                email="admin@example.com",
                hashed_password=get_password_hash("AdminPass1"),
                company_name="QOSYU Admin",
                role=UserRole.ADMIN,
            )
            self.sme = User(
                email="sme@example.com",
                hashed_password=get_password_hash("SmePass123"),
                company_name="Coffee 100%",
                role=UserRole.SME,
            )
            self.recycler = User(
                email="recycler@example.com",
                hashed_password=get_password_hash("RecPass123"),
                company_name="EcoRecycler",
                role=UserRole.RECYCLER,
            )
            db.add_all([self.admin, self.sme, self.recycler])
            await db.commit()
            for u in (self.admin, self.sme, self.recycler):
                await db.refresh(u)

        self.admin_hdr = {"Authorization": f"Bearer {create_access_token(self.admin.id, 'admin')[0]}"}
        self.sme_hdr = {"Authorization": f"Bearer {create_access_token(self.sme.id, 'sme')[0]}"}
        self.rec_hdr = {"Authorization": f"Bearer {create_access_token(self.recycler.id, 'recycler')[0]}"}

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_admin_can_view_pilot_applications_and_non_admin_is_blocked(self):
        created = await self.client.post(
            "/public/pilot",
            json={
                "company_name": "Bakery Atyrau",
                "contact": "@bakery_kz",
                "comment": "20 kg cardboard weekly",
                "language": "ru",
            },
        )
        self.assertEqual(created.status_code, 201)

        self.assertEqual(
            (await self.client.get("/admin/pilot-applications", headers=self.sme_hdr)).status_code,
            403,
        )
        resp = await self.client.get("/admin/pilot-applications", headers=self.admin_hdr)
        self.assertEqual(resp.status_code, 200, resp.text)
        items = resp.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["company_name"], "Bakery Atyrau")
        self.assertEqual(items[0]["contact"], "@bakery_kz")

    async def test_admin_user_search_escapes_sql_wildcards(self):
        resp = await self.client.get("/admin/users?search=%25", headers=self.admin_hdr)
        self.assertEqual(resp.status_code, 200)
        # Только "Coffee 100%" содержит литерал '%', а не все пользователи
        emails = [u["email"] for u in resp.json()]
        self.assertEqual(emails, ["sme@example.com"])

    async def test_marketplace_order_transitions_and_inventory_restoration(self):
        listing = await self.client.post(
            "/marketplace/listings",
            headers=self.sme_hdr,
            json={
                "waste_type": "cardboard",
                "price_per_kg": 45,
                "min_kg": 10,
                "available_kg": 100,
                "description": "Clean dry boxes",
            },
        )
        self.assertEqual(listing.status_code, 201, listing.text)
        lid = listing.json()["id"]

        # Нельзя купить собственное объявление
        self.assertEqual(
            (
                await self.client.post(
                    "/marketplace/orders",
                    headers=self.sme_hdr,
                    json={"listing_id": lid, "quantity_kg": 20},
                )
            ).status_code,
            409,
        )

        # Покупатель создаёт заказ — остаток уменьшается до 70
        order = await self.client.post(
            "/marketplace/orders",
            headers=self.rec_hdr,
            json={"listing_id": lid, "quantity_kg": 30},
        )
        self.assertEqual(order.status_code, 201, order.text)
        self.assertEqual(order.json()["total"], 1350.0)
        oid = order.json()["order_id"]

        view = await self.client.get(f"/marketplace/listings/{lid}")
        self.assertEqual(view.status_code, 200)
        self.assertEqual(view.json()["available_kg"], 70.0)
        self.assertEqual(view.json()["views"], 1)

        # Покупатель не может сам себе принять заказ
        self.assertEqual(
            (
                await self.client.put(
                    f"/marketplace/orders/{oid}/status",
                    headers=self.rec_hdr,
                    json={"status": "accepted"},
                )
            ).status_code,
            409,
        )

        # Покупатель отменяет pending-заказ — остаток возвращается до 100
        cancelled = await self.client.put(
            f"/marketplace/orders/{oid}/status",
            headers=self.rec_hdr,
            json={"status": "cancelled"},
        )
        self.assertEqual(cancelled.status_code, 200)
        view2 = await self.client.get(f"/marketplace/listings/{lid}")
        self.assertEqual(view2.json()["available_kg"], 100.0)
        self.assertEqual(view2.json()["views"], 2)


if __name__ == "__main__":
    unittest.main()
