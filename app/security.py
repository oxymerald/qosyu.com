"""Rate limiting, security headers и лимит размера тела запроса."""

import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import settings

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None


class RateLimiter:
    """Фиксированное окно на Redis c fallback на память процесса.

    Fallback нужен, чтобы API оставался защищённым, даже если Redis недоступен.
    """

    def __init__(self):
        self._redis = None
        self._local: dict[str, tuple[int, float]] = {}

    async def init(self):
        if aioredis is None:
            return
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
            )
            await self._redis.ping()
        except Exception:
            self._redis = None

    async def close(self):
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """True — запрос разрешён, False — лимит исчерпан."""
        if self._redis is not None:
            try:
                full_key = f"rl:{key}"
                count = await self._redis.incr(full_key)
                if count == 1:
                    await self._redis.expire(full_key, window_seconds)
                return count <= limit
            except Exception:
                pass  # Redis отвалился — переходим на локальный счётчик
        now = time.monotonic()
        count, started = self._local.get(key, (0, now))
        if now - started >= window_seconds:
            count, started = 0, now
        count += 1
        self._local[key] = (count, started)
        if len(self._local) > 50_000:  # защита от разрастания памяти
            cutoff = now - 3600
            self._local = {k: v for k, v in self._local.items() if v[1] > cutoff}
        return count <= limit


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window_seconds: int):
    """FastAPI-зависимость: не более `limit` запросов за окно с одного IP."""

    async def dependency(request: Request):
        key = f"{scope}:{client_ip(request)}"
        if not await rate_limiter.hit(key, limit, window_seconds):
            raise HTTPException(
                status_code=429,
                detail="Слишком много запросов. Попробуйте позже.",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    CSP = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: https://*.basemaps.cartocdn.com https://unpkg.com; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=()")
        response.headers.setdefault("Content-Security-Policy", self.CSP)
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > settings.MAX_BODY_SIZE:
                    return JSONResponse(
                        status_code=413, content={"detail": "Тело запроса слишком большое"}
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Некорректный запрос"})
        return await call_next(request)
