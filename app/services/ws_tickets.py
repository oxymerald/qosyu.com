"""Одноразовые короткоживущие тикеты для подключения к WebSocket-чату.

Исключают передачу долгоживущего JWT в URL query string.
Тикет живёт 30 секунд, привязан к (user_id, receiver_id) и уничтожается при использовании.
"""

import secrets
import time

from security import rate_limiter

TICKET_TTL_SECONDS = 30
_local: dict[str, tuple[int, int, float]] = {}


def _prune_local(now: float) -> None:
    if len(_local) > 10_000:
        for key in [k for k, (_, _, exp) in _local.items() if exp < now]:
            _local.pop(key, None)


async def issue(user_id: int, receiver_id: int) -> str:
    ticket = secrets.token_urlsafe(32)
    payload = f"{user_id}:{receiver_id}"
    redis = rate_limiter._redis
    if redis is not None:
        try:
            await redis.set(f"ws-ticket:{ticket}", payload, ex=TICKET_TTL_SECONDS)
            return ticket
        except Exception:
            pass
    now = time.monotonic()
    _prune_local(now)
    _local[ticket] = (user_id, receiver_id, now + TICKET_TTL_SECONDS)
    return ticket


async def redeem(ticket: str, receiver_id: int) -> int | None:
    ticket = ticket.strip()
    if len(ticket) < 16 or len(ticket) > 128:
        return None
    redis = rate_limiter._redis
    if redis is not None:
        try:
            key = f"ws-ticket:{ticket}"
            raw = await redis.getdel(key)
            if raw is None:
                return None
            value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            uid_str, rid_str = value.split(":", 1)
            if int(rid_str) != receiver_id:
                return None
            return int(uid_str)
        except Exception:
            pass
    entry = _local.pop(ticket, None)
    if entry is None:
        return None
    user_id, expected_receiver, expires = entry
    if time.monotonic() > expires or expected_receiver != receiver_id:
        return None
    return user_id
