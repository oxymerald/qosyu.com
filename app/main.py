import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from auth import get_password_hash
from config import settings
from database import async_session_maker, engine
from models import Base, User, UserRole
from routers import (
    admin,
    ai,
    analytics,
    auth,
    chat,
    clustering,
    marketplace,
    push,
    recycler,
    requests,
    reviews,
    telegram_bot,
)
from security import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    rate_limiter,
)

logger = logging.getLogger("qosyu")
logging.basicConfig(level=logging.INFO)


async def _bootstrap_admin():
    """Создаёт администратора из ADMIN_EMAIL/ADMIN_PASSWORD, если его ещё нет."""
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL.lower()))
        if result.scalar_one_or_none() is None:
            db.add(
                User(
                    email=settings.ADMIN_EMAIL.lower(),
                    hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
                    company_name="QOSYU Admin",
                    role=UserRole.ADMIN,
                )
            )
            await db.commit()
            logger.info("Создан администратор %s", settings.ADMIN_EMAIL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await rate_limiter.init()
    await _bootstrap_admin()

    bot_task = None
    if settings.TELEGRAM_BOT_TOKEN:
        bot_task = asyncio.create_task(telegram_bot.run_bot())
    else:
        logger.info("TELEGRAM_BOT_TOKEN не задан — бот не запускается")

    yield

    if bot_task:
        bot_task.cancel()
    await rate_limiter.close()
    await engine.dispose()


app = FastAPI(
    title="QOSYU API",
    description="Цифровая платформа первой мили экологической логистики",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# --- Middleware (порядок: снаружи внутрь) ---
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
if settings.trusted_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Не раскрываем стектрейсы и внутренности наружу
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


# --- Роутеры API ---
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(requests.router, prefix="/requests", tags=["requests"])
app.include_router(recycler.router, prefix="/recycler", tags=["recycler"])
app.include_router(clustering.router, prefix="/clustering", tags=["clustering"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(chat.router)
app.include_router(marketplace.router)
app.include_router(reviews.router)
app.include_router(push.router)
app.include_router(admin.router)
app.include_router(ai.router)


@app.get("/health", tags=["service"])
async def health():
    return {"status": "ok"}


# --- Статика и фронтенд ---
class CachedStaticFiles(StaticFiles):
    """Статика с кэшированием в браузере (у файлов есть ETag для инвалидации)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response


app.mount("/static", CachedStaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse("static/index.html")
