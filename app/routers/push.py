from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import PushSubscription
from dependencies import get_current_user
from config import settings
from pywebpush import webpush, WebPushException
import json

router = APIRouter(prefix="/push", tags=["push"])

@router.post("/subscribe")
async def subscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    data = await request.json()
    sub = PushSubscription(
        user_id=current_user.id,
        endpoint=data["endpoint"],
        p256dh=data["keys"]["p256dh"],
        auth=data["keys"]["auth"],
        user_agent=request.headers.get("user-agent")
    )
    db.add(sub)
    await db.commit()
    return {"status": "subscribed"}

@router.post("/unsubscribe")
async def unsubscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    data = await request.json()
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == data["endpoint"]
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        await db.delete(sub)
        await db.commit()
    return {"status": "unsubscribed"}

async def send_push_notification(user_id: int, title: str, body: str, db: AsyncSession, data: dict = None):
    result = await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
    subs = result.scalars().all()
    payload = json.dumps({"title": title, "body": body, "data": data or {}})
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_EMAIL}"}
            )
        except WebPushException as e:
            if e.response and e.response.status_code in [410, 404]:
                await db.delete(sub)
                await db.commit()
    return len(subs)