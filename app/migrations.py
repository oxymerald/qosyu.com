"""Additive, repeatable upgrades for existing installations. Never erase data."""
from sqlalchemy import text


async def upgrade_schema(conn):
    # Serialize application startup across workers; released with the transaction.
    await conn.execute(text("SELECT pg_advisory_xact_lock(71609521)"))
    await conn.execute(text("ALTER TABLE waste_requests ADD COLUMN IF NOT EXISTS address VARCHAR(300)"))
    await conn.execute(text("ALTER TABLE waste_requests ADD COLUMN IF NOT EXISTS pickup_note VARCHAR(500)"))
