"""Одноразовые коды привязки Telegram-аккаунта к веб-аккаунту.

Код живёт 10 минут, хранится в Redis (fallback — память процесса),
удаляется при использовании.
"""

import secrets
import time

from security import rate_limiter

CODE_TTL_SECONDS = 600
_local: dict[str, tuple[int, float]] = {}


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def issue(user_id: int) -> str:
    code = _generate_code()
    redis = rate_limiter._redis
    if redis is not None:
        try:
            await redis.set(f"tg-link:{code}", str(user_id), ex=CODE_TTL_SECONDS)
            return code
        except Exception:
            pass
    now = time.monotonic()
    # подчистка просроченных
    for key in [k for k, (_, exp) in _local.items() if exp < now]:
        _local.pop(key, None)
    _local[code] = (user_id, now + CODE_TTL_SECONDS)
    return code


async def redeem(code: str) -> int | None:
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return None
    redis = rate_limiter._redis
    if redis is not None:
        try:
            key = f"tg-link:{code}"
            value = await redis.get(key)
            if value is not None:
                await redis.delete(key)
                return int(value)
            return None
        except Exception:
            pass
    entry = _local.pop(code, None)
    if entry is None:
        return None
    user_id, expires = entry
    if time.monotonic() > expires:
        return None
    return user_id
