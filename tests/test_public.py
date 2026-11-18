"""Guest intake uses an isolated SQLite database; never starts the app lifespan."""
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from config import settings
from database import get_db
from main import app
from models import PilotApplication
from public_pages import COPY
from security import rate_limiter


class PublicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as connection:
            await connection.execute(text(f"ATTACH DATABASE ':memory:' AS {settings.DATABASE_SCHEMA}"))
            await connection.run_sync(PilotApplication.__table__.create)

        async def isolated_db():
            async with AsyncSession(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        rate_limiter._local.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_guest_submission_is_committed_without_authentication(self):
        response = await self.client.post("/public/pilot", json={
            "company_name": "  Test cafe  ", "contact": "  test@example.com  ",
            "comment": "Please discuss pickup windows.", "language": "en",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json(), {"accepted": True})
        async with AsyncSession(self.engine) as db:
            saved = (await db.execute(select(PilotApplication))).scalar_one()
            self.assertEqual(saved.company_name, "Test cafe")
            self.assertEqual(saved.contact, "test@example.com")
            self.assertEqual(saved.language, "en")
        # No public endpoint may expose the saved contacts.
        self.assertEqual((await self.client.get("/public/pilot")).status_code, 405)

    async def test_invalid_or_oversized_fields_do_not_create_an_application(self):
        for payload in [
            {"company_name": "  ", "contact": "abc"},
            {"company_name": "Cafe", "contact": "x"},
            {"company_name": "Cafe", "contact": "abc", "comment": "x" * 2001},
            {"company_name": "Cafe", "contact": "abc", "language": "xx"},
            {"company_name": "Cafe", "contact": "abc", "unexpected": "value"},
        ]:
            self.assertEqual((await self.client.post("/public/pilot", json=payload)).status_code, 422)
        async with AsyncSession(self.engine) as db:
            self.assertEqual((await db.execute(select(PilotApplication))).scalars().all(), [])

    async def test_intake_is_rate_limited(self):
        payload = {"company_name": "Cafe", "contact": "test@example.com"}
        for _ in range(5):
            self.assertEqual((await self.client.post("/public/pilot", json=payload)).status_code, 201)
        response = await self.client.post("/public/pilot", json=payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "3600")

    async def test_database_failure_is_not_reported_as_success(self):
        failing_db = AsyncMock(spec=AsyncSession)
        failing_db.add = lambda _: None
        failing_db.commit.side_effect = RuntimeError("isolated database failure")

        async def unavailable_db():
            yield failing_db

        app.dependency_overrides[get_db] = unavailable_db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver") as client:
            response = await client.post("/public/pilot", json={"company_name": "Cafe", "contact": "test@example.com"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("isolated database failure", response.text)

    async def test_localized_metadata_and_legal_urls_are_available_without_js(self):
        for lang, copy in COPY.items():
            response = await self.client.get(f"/?lang={lang}")
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'<html lang="{lang}">', response.text)
            self.assertIn(copy["description"], response.text)
            self.assertIn('property="og:description"', response.text)
            self.assertIn('<div class="product-scheme" data-nosnippet>', response.text)
            self.assertIn('<div class="cabinet-tabs" id="cabinetTabs" data-nosnippet>', response.text)
            self.assertIn('<section class="tab-pane hidden" id="pane-admin" data-nosnippet>', response.text)
            for path in ["privacy", "terms"]:
                legal = await self.client.get(f"/{path}?lang={lang}")
                self.assertEqual(legal.status_code, 200)
                self.assertIn(copy[path], legal.text)
                self.assertIn(f'<html lang="{lang}">', legal.text)
                if path == "privacy":
                    self.assertIn("Gemini API", legal.text)
        self.assertIn('<html lang="ru">', (await self.client.get("/?lang=invalid")).text)

    async def test_contact_links_in_pilot_and_footer_for_all_locales(self):
        locations = {"ru": "Атырау, Казахстан", "en": "Atyrau, Kazakhstan", "kk": "Атырау, Қазақстан"}
        with patch.multiple(settings,
            CONTACT_LOCATION=locations["ru"], CONTACT_LOCATION_EN=locations["en"], CONTACT_LOCATION_KK=locations["kk"],
            CONTACT_EMAIL="hello@example.com", CONTACT_PHONE="+7 701 555 0100",
            CONTACT_INSTAGRAM="@test.qosyu", CONTACT_TIKTOK="@test.qosyu",
            CONTACT_TELEGRAM="", CONTACT_WHATSAPP="",
        ):
            for lang, location in locations.items():
                response = await self.client.get(f"/?lang={lang}")
                pilot = response.text.split('id="pricing"', 1)[1].split("</section>", 1)[0]
                footer = response.text.split('id="mainFooter"', 1)[1].split("</footer>", 1)[0]
                for section in (pilot, footer):
                    self.assertIn(f">{location}</span>", section)
                    self.assertIn('href="mailto:hello@example.com"', section)
                    self.assertIn('href="tel:+77015550100">+7 701 555 0100</a>', section)
                    self.assertIn('href="https://www.instagram.com/test.qosyu/"', section)
                    self.assertIn('href="https://www.tiktok.com/@test.qosyu"', section)
                    for missing in ("Telegram", "WhatsApp", "заглуш", "Placeholder", "TODO"):
                        self.assertNotIn(missing, section)

    async def test_unset_contacts_omit_the_entire_empty_block(self):
        fields = {name: "" for name in type(settings).model_fields if name.startswith("CONTACT_")}
        with patch.multiple(settings, **fields):
            response = await self.client.get("/")
            self.assertNotIn('class="public-contacts"', response.text)
            self.assertNotIn("PUBLIC_CONTACTS", response.text)
            privacy = await self.client.get("/privacy")
            self.assertNotIn("mailto:", privacy.text)
        fields["CONTACT_TELEGRAM"] = "@qosyu_test"
        fields["CONTACT_WHATSAPP"] = "+77001234567"
        with patch.multiple(settings, **fields):
            response = await self.client.get("/")
            self.assertEqual(response.text.count('href="https://t.me/qosyu_test"'), 2)
            self.assertEqual(response.text.count('href="https://wa.me/77001234567"'), 2)
            self.assertNotIn("tel:", response.text)
            self.assertNotIn("mailto:", response.text)


if __name__ == "__main__":
    unittest.main()
