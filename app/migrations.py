"""Additive, repeatable upgrades for existing installations. Never erase data."""
from sqlalchemy import MetaData, text

from models import PilotApplication


async def upgrade_schema(conn, schema: str):
    # Serialize application startup across workers; released with the transaction.
    await conn.execute(text("SELECT pg_advisory_xact_lock(71609521)"))
    identifier = conn.dialect.identifier_preparer.quote_identifier(schema)
    await conn.execute(text(f"ALTER TABLE {identifier}.waste_requests ADD COLUMN IF NOT EXISTS address VARCHAR(300)"))
    await conn.execute(text(f"ALTER TABLE {identifier}.waste_requests ADD COLUMN IF NOT EXISTS pickup_note VARCHAR(500)"))
    pilot = PilotApplication.__table__
    if pilot.schema != schema:
        pilot = pilot.to_metadata(MetaData(), schema=schema)
    await conn.run_sync(pilot.create, checkfirst=True)
