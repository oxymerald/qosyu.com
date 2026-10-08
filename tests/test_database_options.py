import os
import ssl
import unittest
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import text

from config import Settings
from database import engine
from database_options import database_options


def config(url, **overrides):
    values = dict(DATABASE_URL=url, DATABASE_SCHEMA="qosyu", DATABASE_SSL=False,
                  DATABASE_SSL_CA_FILE="", DATABASE_POOL_SIZE=2, DATABASE_MAX_OVERFLOW=1)
    values.update(overrides)
    return SimpleNamespace(**values)


class DatabaseOptionsTests(unittest.TestCase):
    def test_session_pooler_enforces_verified_tls_and_small_pool(self):
        url, opts = database_options(config(
            "postgresql://postgres.example:p%40ss@aws-example.pooler.supabase.com:5432/postgres?sslmode=require"
        ))
        self.assertEqual(url.drivername, "postgresql+asyncpg")
        self.assertEqual(url.password, "p@ss")
        self.assertNotIn("sslmode", url.query)
        context = opts["connect_args"]["ssl"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(opts["pool_size"], 2)
        self.assertEqual(opts["max_overflow"], 1)
        self.assertEqual(opts["connect_args"]["server_settings"]["search_path"], '"qosyu", extensions, public')

    def test_local_connection_stays_plain_and_preserves_password(self):
        url, opts = database_options(config("postgresql+asyncpg://local:local@db:5432/test"))
        self.assertNotIn("ssl", opts["connect_args"])
        self.assertEqual(url.host, "db")

    def test_transaction_pooler_rejected_without_disclosing_password(self):
        with self.assertRaisesRegex(ValueError, "Session pooler") as result:
            database_options(config("postgres://user:private-value@host.pooler.supabase.com:6543/postgres"))
        self.assertNotIn("private-value", str(result.exception))

    def test_supabase_cannot_disable_tls_via_url(self):
        _, opts = database_options(config("postgres://user:p@db.example.supabase.co:5432/postgres?sslmode=disable"))
        self.assertTrue(opts["connect_args"]["ssl"].check_hostname)

    def test_invalid_url_has_sanitized_error(self):
        with self.assertRaises(ValueError) as result:
            database_options(config("not-a-url-private-value"))
        self.assertNotIn("private-value", str(result.exception))

    def test_schema_name_cannot_inject_sql(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, DATABASE_SCHEMA='public"; DROP SCHEMA public;--')


@unittest.skipUnless(os.getenv("QOSYU_ISOLATED_TEST") == "1", "isolated DB only")
class PrivateSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_tables_are_private_with_rls_and_postgis_works(self):
        async with engine.connect() as conn:
            schema = (await conn.execute(text("SELECT current_schema()"))).scalar_one()
            self.assertEqual(schema, "qosyu_test")
            rows = (await conn.execute(text(
                "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON c.relnamespace=n.oid "
                "WHERE n.nspname=current_schema() AND c.relkind='r'"
            ))).all()
            self.assertGreaterEqual(len(rows), 9)
            self.assertTrue(all(row.relrowsecurity for row in rows))
            self.assertEqual((await conn.execute(text("SELECT ST_X(ST_Point(51.9, 47.1))"))).scalar_one(), 51.9)
            self.assertIsNone((await conn.execute(text("SELECT to_regclass('public.users')"))).scalar_one())
        await engine.dispose()
