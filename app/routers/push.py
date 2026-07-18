import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import get_current_user
from models import PushSubscription, User
from schemas import PushSubscribe, PushUnsubscribe
from security import rate_limit

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover
    webpush = None

router = APIRouter(prefix="/push", tags=["push"])


def _require_vapid():
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY or webpush is None:
        raise HTTPException(status_code=503, detail="Push-уведомления не настроены")


@router.get("/public-key")
async def public_key():
    _require_vapid()
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.post(
    "/subscribe",
    dependencies=[Depends(rate_limit("push-subscribe", limit=20, window_seconds=3600))],
)
async def subscribe(
    data: PushSubscribe,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_vapid()
    existing = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    sub = existing.scalar_one_or_none()
    if sub:
        sub.user_id = current_user.id
        sub.p256dh = data.keys.p256dh
        sub.auth = data.keys.auth
    else:
        db.add(
            PushSubscription(
                user_id=current_user.id,
                endpoint=data.endpoint,
                p256dh=data.keys.p256dh,
                auth=data.keys.auth,
                user_agent=(request.headers.get("user-agent") or "")[:500],
            )
        )
    await db.commit()
    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(
    data: PushUnsubscribe,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == data.endpoint,
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        await db.delete(sub)
        await db.commit()
    return {"status": "unsubscribed"}


async def send_push_notification(
    user_id: int, title: str, body: str, db: AsyncSession, data: dict | None = None
) -> int:
    if not settings.VAPID_PRIVATE_KEY or webpush is None:
        return 0
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user_id)
    )
    subs = result.scalars().all()
    payload = json.dumps({"title": title, "body": body, "data": data or {}})
    delivered = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_EMAIL}"},
            )
            delivered += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                await db.delete(sub)
                await db.commit()
    return delivered
