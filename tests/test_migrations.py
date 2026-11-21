import os
import unittest
import uuid
from sqlalchemy import text
from database import engine
from migrations import upgrade_schema
from schemas import WasteRequestCreate
from pydantic import ValidationError


class PickupValidationTests(unittest.TestCase):
    def test_optional_trimmed_and_bounded_details(self):
        args = dict(waste_type="cardboard", weight_kg=12, latitude=47, longitude=51)
        self.assertIsNone(WasteRequestCreate(**args).address)
        value = WasteRequestCreate(**args, address="  Abay 1  ", pickup_note="  ")
        self.assertEqual(value.address, "Abay 1")
        self.assertIsNone(value.pickup_note)
        for field, length in [("address", 301), ("pickup_note", 501)]:
            with self.assertRaises(ValidationError):
                WasteRequestCreate(**args, **{field: "x" * length})


@unittest.skipUnless(os.getenv("QOSYU_ISOLATED_TEST") == "1", "isolated DB only")
class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_table_survives_repeated_upgrade(self):
        schema = "migration_test_" + uuid.uuid4().hex
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text("CREATE TABLE waste_requests (id INTEGER PRIMARY KEY, weight_kg FLOAT NOT NULL)"))
                await conn.execute(text("INSERT INTO waste_requests VALUES (17, 25.5)"))
                await upgrade_schema(conn, schema)
                await conn.execute(text(f"""INSERT INTO "{schema}".pilot_applications
                    (company_name, contact, comment, language) VALUES ('Cafe', 'test@example.com', '', 'en')"""))
                await upgrade_schema(conn, schema)
                pilot = (await conn.execute(text(f'SELECT company_name FROM "{schema}".pilot_applications'))).scalar_one()
                self.assertEqual(pilot, "Cafe")
                row = (await conn.execute(text("SELECT id, weight_kg, address, pickup_note FROM waste_requests"))).one()
                self.assertEqual(tuple(row), (17, 25.5, None, None))
            finally:
                await transaction.rollback()
        await engine.dispose()

    async def test_users_table_gets_token_version_idempotently(self):
        schema = "migration_users_" + uuid.uuid4().hex
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text("CREATE TABLE waste_requests (id INTEGER PRIMARY KEY, sme_id INTEGER, status TEXT, created_at TIMESTAMPTZ)"))
                await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)"))
                await conn.execute(text("INSERT INTO users VALUES (1, 'old@example.com')"))
                await upgrade_schema(conn, schema)
                await upgrade_schema(conn, schema)
                row = (await conn.execute(text("SELECT id, email, token_version FROM users"))).one()
                self.assertEqual(tuple(row), (1, "old@example.com", 0))
            finally:
                await transaction.rollback()
        await engine.dispose()
