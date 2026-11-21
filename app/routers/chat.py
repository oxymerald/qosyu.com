import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker, get_db
from dependencies import get_current_user
from models import ChatMessage, User, UserRole
from security import rate_limit
from services import ws_tickets
from services.chat_manager import manager

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_MESSAGE_LEN = 2000
# Не более 20 сообщений за 10 секунд с одного соединения
WS_RATE_LIMIT = 20
WS_RATE_WINDOW = 10.0


class WsTicketIn(BaseModel):
    receiver_id: int = Field(..., gt=0)


async def _can_message(db: AsyncSession, sender: User, receiver: User) -> bool:
    if sender.id == receiver.id:
        return False
    if sender.role == UserRole.ADMIN:
        return True
    if receiver.role == UserRole.ADMIN:
        # Неадмин может отвечать админу, только если диалог уже существует.
        existing = await db.scalar(
            select(ChatMessage.id)
            .where(
                (
                    (ChatMessage.from_user_id == receiver.id)
                    & (ChatMessage.to_user_id == sender.id)
                )
                | (
                    (ChatMessage.from_user_id == sender.id)
                    & (ChatMessage.to_user_id == receiver.id)
                )
            )
            .limit(1)
        )
        return existing is not None
    return sender.role != receiver.role


@router.post(
    "/ws-ticket",
    dependencies=[Depends(rate_limit("ws-ticket", limit=60, window_seconds=60))],
)
async def issue_ws_ticket(
    data: WsTicketIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Выдаёт одноразовый 30-секундный тикет для WebSocket (JWT не попадает в URL)."""
    if data.receiver_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя открыть чат с самим собой")
    receiver = await db.get(User, data.receiver_id)
    if receiver is None or not receiver.is_active:
        raise HTTPException(status_code=404, detail="Собеседник не найден")
    if not await _can_message(db, current_user, receiver):
        raise HTTPException(status_code=403, detail="Диалог с этим пользователем недоступен")
    ticket = await ws_tickets.issue(current_user.id, receiver.id)
    return {"ticket": ticket, "expires_in": ws_tickets.TICKET_TTL_SECONDS}


@router.websocket("/ws/{receiver_id}")
async def websocket_chat(
    websocket: WebSocket,
    receiver_id: int,
    ticket: str = Query(..., min_length=16, max_length=128),
):
    user_id = await ws_tickets.redeem(ticket, receiver_id)
    if user_id is None:
        await websocket.close(code=1008)
        return

    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active or user.id == receiver_id:
            await websocket.close(code=1008)
            return
        receiver = await db.get(User, receiver_id)
        if receiver is None or not receiver.is_active or not await _can_message(db, user, receiver):
            await websocket.close(code=1008)
            return

        await manager.connect(user.id, websocket)

        # Открытие диалога помечает входящие от собеседника как прочитанные
        await db.execute(
            update(ChatMessage)
            .where(
                ChatMessage.from_user_id == receiver_id,
                ChatMessage.to_user_id == user.id,
                ChatMessage.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        await db.commit()

    sent_times: list[float] = []
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_MESSAGE_LEN * 4:
                continue
            try:
                msg_data = json.loads(raw)
                text = str(msg_data.get("message", "")).strip()
            except (json.JSONDecodeError, AttributeError):
                continue
            if not text or len(text) > MAX_MESSAGE_LEN:
                continue

            now = time.monotonic()
            sent_times = [t for t in sent_times if now - t < WS_RATE_WINDOW]
            if len(sent_times) >= WS_RATE_LIMIT:
                await websocket.send_json(
                    {"type": "error", "detail": "Слишком много сообщений, подождите"}
                )
                continue
            sent_times.append(now)

            async with async_session_maker() as db:
                new_msg = ChatMessage(
                    from_user_id=user.id, to_user_id=receiver_id, message=text, is_read=False
                )
                db.add(new_msg)
                await db.commit()
                await db.refresh(new_msg)

            payload = {
                "type": "message",
                "id": new_msg.id,
                "from": user.id,
                "from_name": user.company_name or "Пользователь",
                "message": text,
                "time": new_msg.created_at.isoformat() if new_msg.created_at else None,
            }
            await manager.send_message(receiver_id, payload)
            await websocket.send_json({**payload, "own": True})
    except WebSocketDisconnect:
        manager.disconnect(user.id, websocket)


@router.get("/history/{user_id}")
async def get_chat_history(
    user_id: int,
    limit: int = Query(50, ge=1, le=100),
    before: int | None = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(ChatMessage).where(
        ((ChatMessage.from_user_id == current_user.id) & (ChatMessage.to_user_id == user_id))
        | ((ChatMessage.from_user_id == user_id) & (ChatMessage.to_user_id == current_user.id))
    )
    if before:
        query = query.where(ChatMessage.id < before)
    query = query.order_by(ChatMessage.id.desc()).limit(limit)
    result = await db.execute(query)
    messages = result.scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "from": m.from_user_id,
                "to": m.to_user_id,
                "message": m.message,
                "is_read": m.is_read,
                "time": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ],
        "has_more": len(messages) == limit,
    }


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.to_user_id == current_user.id,
            ChatMessage.is_read == False,  # noqa: E712
        )
    )
    return {"unread": result.scalar() or 0}


@router.get("/conversations")
async def get_conversations(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(ChatMessage)
        .where(
            (ChatMessage.from_user_id == current_user.id)
            | (ChatMessage.to_user_id == current_user.id)
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(500)
    )
    messages = result.scalars().all()
    latest_by_other: dict[int, ChatMessage] = {}
    for msg in messages:
        other_id = msg.from_user_id if msg.to_user_id == current_user.id else msg.to_user_id
        if other_id not in latest_by_other:
            latest_by_other[other_id] = msg

    if not latest_by_other:
        return []

    users_rows = (
        await db.execute(select(User).where(User.id.in_(list(latest_by_other.keys()))))
    ).scalars().all()
    users_by_id = {u.id: u for u in users_rows}

    conversations: dict[int, dict] = {}
    for other_id, msg in latest_by_other.items():
        other = users_by_id.get(other_id)
        conversations[other_id] = {
            "user_id": other_id,
            "name": (other.company_name or "Пользователь") if other else "Пользователь",
            "last_message": msg.message,
            "last_time": msg.created_at.isoformat() if msg.created_at else None,
            "unread": 0,
        }

    unread_result = await db.execute(
        select(ChatMessage.from_user_id, func.count(ChatMessage.id))
        .where(
            ChatMessage.to_user_id == current_user.id,
            ChatMessage.is_read == False,  # noqa: E712
        )
        .group_by(ChatMessage.from_user_id)
    )
    for from_id, count in unread_result.all():
        if from_id in conversations:
            conversations[from_id]["unread"] = count
    return list(conversations.values())


@router.get("/partners")
async def get_chat_partners(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Пользователи противоположной роли, с которыми можно начать диалог."""
    target_role = UserRole.RECYCLER if current_user.role == UserRole.SME else UserRole.SME
    result = await db.execute(
        select(User)
        .where(User.role == target_role, User.is_active == True, User.id != current_user.id)  # noqa: E712
        .limit(100)
    )
    return [
        {"user_id": u.id, "name": u.company_name or "Пользователь", "rating": u.rating_avg or 0}
        for u in result.scalars().all()
    ]
