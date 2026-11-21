"""Rate limiting, security headers и лимит размера тела запроса."""

import time

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
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
        if aioredis is None or not settings.REDIS_URL:
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


class SecurityHeadersMiddleware:
    CSP = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org https://unpkg.com; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=()")
                headers.setdefault("Content-Security-Policy", self.CSP)
                if settings.is_production:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


class PayloadTooLargeError(Exception):
    """Тело HTTP-запроса превысило MAX_BODY_SIZE при чтении потока."""


class BodySizeLimitMiddleware:
    """Ограничивает размер тела HTTP-запроса по Content-Length и реальному потоку байтов."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length.decode("latin-1"))
            except ValueError:
                await JSONResponse(status_code=400, content={"detail": "Некорректный запрос"})(
                    scope, receive, send
                )
                return
            if content_length < 0:
                await JSONResponse(status_code=400, content={"detail": "Некорректный запрос"})(
                    scope, receive, send
                )
                return
            if content_length > settings.MAX_BODY_SIZE:
                await JSONResponse(
                    status_code=413, content={"detail": "Тело запроса слишком большое"}
                )(scope, receive, send)
                return

        received_bytes = 0
        response_started = False

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > settings.MAX_BODY_SIZE:
                    raise PayloadTooLargeError()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except PayloadTooLargeError:
            if not response_started:
                await JSONResponse(
                    status_code=413, content={"detail": "Тело запроса слишком большое"}
                )(scope, receive, send)
