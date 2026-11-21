"""Additive, repeatable upgrades for existing installations. Never erase data."""
from sqlalchemy import MetaData, text

from models import PilotApplication


async def _ensure_index(
    conn, schema: str, table: str, index_name: str, columns: tuple[str, ...], columns_sql: str
) -> None:
    identifier = conn.dialect.identifier_preparer.quote_identifier(schema)
    existing = set(
        (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            )
        ).scalars()
    )
    if set(columns).issubset(existing):
        await conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {identifier}.{table} ({columns_sql})")
        )


async def upgrade_schema(conn, schema: str):
    # Serialize application startup across workers; released with the transaction.
    await conn.execute(text("SELECT pg_advisory_xact_lock(71609521)"))
    identifier = conn.dialect.identifier_preparer.quote_identifier(schema)
    await conn.execute(text(f"ALTER TABLE {identifier}.waste_requests ADD COLUMN IF NOT EXISTS address VARCHAR(300)"))
    await conn.execute(text(f"ALTER TABLE {identifier}.waste_requests ADD COLUMN IF NOT EXISTS pickup_note VARCHAR(500)"))
    await conn.execute(
        text(f"ALTER TABLE IF EXISTS {identifier}.users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")
    )
    pilot = PilotApplication.__table__
    if pilot.schema != schema:
        pilot = pilot.to_metadata(MetaData(), schema=schema)
    await conn.run_sync(pilot.create, checkfirst=True)

    # Hot-path indexes (safe on both fresh and pre-existing installations).
    await _ensure_index(
        conn, schema, "waste_requests", "ix_waste_requests_sme_created", ("sme_id", "created_at"), "sme_id, created_at DESC"
    )
    await _ensure_index(conn, schema, "waste_requests", "ix_waste_requests_status", ("status",), "status")
    await _ensure_index(
        conn, schema, "collection_zones", "ix_collection_zones_status_recycler", ("status", "recycler_id"), "status, recycler_id"
    )
    await _ensure_index(
        conn, schema, "chat_messages", "ix_chat_messages_to_unread", ("to_user_id", "is_read"), "to_user_id, is_read"
    )
    await _ensure_index(
        conn, schema, "chat_messages", "ix_chat_messages_pair_id", ("from_user_id", "to_user_id", "id"), "from_user_id, to_user_id, id DESC"
    )
    await _ensure_index(conn, schema, "marketplace_orders", "ix_marketplace_orders_buyer", ("buyer_id",), "buyer_id")
    await _ensure_index(conn, schema, "marketplace_orders", "ix_marketplace_orders_seller", ("seller_id",), "seller_id")
    await _ensure_index(
        conn, schema, "pilot_applications", "ix_pilot_applications_created", ("created_at",), "created_at DESC"
    )
