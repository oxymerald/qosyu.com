"""Postgres settings shared by local Docker and Supabase session connections."""
import ssl

from sqlalchemy.engine import make_url


def database_options(settings):
    try:
        url = make_url(settings.DATABASE_URL)
    except Exception:
        raise ValueError("DATABASE_URL must be a PostgreSQL connection string") from None
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    url = url.set(drivername="postgresql+asyncpg")
    host = (url.host or "").lower()
    supabase = host.endswith((".supabase.co", ".supabase.com"))
    if supabase and url.port == 6543:
        raise ValueError("Use Supabase Session pooler on port 5432, not Transaction pooler")
    # libpq URLs use sslmode, whereas asyncpg takes an SSL context.
    mode = url.query.get("sslmode")
    if mode and mode not in {"require", "verify-ca", "verify-full", "disable"}:
        raise ValueError("Use sslmode=require or verify-full for an external database")
    ca_file = settings.DATABASE_SSL_CA_FILE or url.query.get("sslrootcert")
    url = url.difference_update_query(["sslmode", "sslrootcert"])
    connect_args = {
        "server_settings": {
            "search_path": f'"{settings.DATABASE_SCHEMA}", extensions, public',
            "application_name": "qosyu",
        },
        "timeout": 15,
        "command_timeout": 60,
    }
    if supabase or settings.DATABASE_SSL or mode in {"require", "verify-ca", "verify-full"}:
        # Validate both hostname and certificate; never silently downgrade TLS.
        connect_args["ssl"] = ssl.create_default_context(cafile=ca_file or None)
    return url, {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_timeout": 20,
        "pool_recycle": 300,
        "connect_args": connect_args,
    }
