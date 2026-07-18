from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database import get_db
from models import User, ChatMessage
from dependencies import get_current_user
from typing import Dict
import json
from datetime import datetime

router = APIRouter(prefix="/chat", tags=["chat"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.pending_messages: Dict[int, list] = {}
    
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        if user_id in self.pending_messages:
            for msg in self.pending_messages[user_id]:
                await websocket.send_json(msg)
            del self.pending_messages[user_id]
    
    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)
    
    async def send_message(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except:
                self.disconnect(user_id)
                self._add_pending(user_id, message)
                return False
        else:
            self._add_pending(user_id, message)
            return False
    
    def _add_pending(self, user_id: int, message: dict):
        if user_id not in self.pending_messages:
            self.pending_messages[user_id] = []
        self.pending_messages[user_id].append(message)

manager = ConnectionManager()

async def get_current_user_ws(token: str, db: AsyncSession):
    from auth import decode_token
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == int(user_id)))
        return result.scalar_one_or_none()
    except:
        return None

@router.websocket("/ws/{receiver_id}")
async def websocket_chat(
    websocket: WebSocket,
    receiver_id: int,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user_ws(token, db)
    if not user:
        await websocket.close(code=1008)
        return
    
    await manager.connect(user.id, websocket)
    
    await db.execute(
        update(ChatMessage)
        .where(ChatMessage.from_user_id == receiver_id, ChatMessage.to_user_id == user.id, ChatMessage.is_read == False)
        .values(is_read=True, read_at=datetime.utcnow())
    )
    await db.commit()
    
    try:
        while True:
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            
            new_msg = ChatMessage(
                from_user_id=user.id,
                to_user_id=receiver_id,
                message=msg_data["message"],
                is_read=False
            )
            db.add(new_msg)
            await db.commit()
            await db.refresh(new_msg)
            
            await manager.send_message(receiver_id, {
                "type": "message",
                "id": new_msg.id,
                "from": user.id,
                "from_name": user.company_name or user.email,
                "message": msg_data["message"],
                "time": new_msg.created_at.isoformat()
            })
            
    except WebSocketDisconnect:
        manager.disconnect(user.id)

@router.get("/history/{user_id}")
async def get_chat_history(
    user_id: int,
    limit: int = 50,
    before: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(ChatMessage).where(
        ((ChatMessage.from_user_id == current_user.id) & (ChatMessage.to_user_id == user_id)) |
        ((ChatMessage.from_user_id == user_id) & (ChatMessage.to_user_id == current_user.id))
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
                "time": m.created_at.isoformat()
            } for m in reversed(messages)
        ],
        "has_more": len(messages) == limit
    }

@router.get("/unread-count")
async def get_unread_count(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.to_user_id == current_user.id, ChatMessage.is_read == False)
    )
    count = len(result.scalars().all())
    return {"unread": count}

@router.get("/conversations")
async def get_conversations(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(ChatMessage)
        .where((ChatMessage.from_user_id == current_user.id) | (ChatMessage.to_user_id == current_user.id))
        .order_by(ChatMessage.created_at.desc())
    )
    messages = result.scalars().all()
    users_map = {}
    for msg in messages:
        other_id = msg.from_user_id if msg.to_user_id == current_user.id else msg.to_user_id
        if other_id not in users_map:
            other = await db.get(User, other_id)
            users_map[other_id] = {
                "user_id": other_id,
                "name": other.company_name or other.email,
                "last_message": msg.message,
                "last_time": msg.created_at.isoformat(),
                "unread": 0
            }
    unread_result = await db.execute(
        select(ChatMessage).where(ChatMessage.to_user_id == current_user.id, ChatMessage.is_read == False)
    )
    for msg in unread_result.scalars().all():
        if msg.from_user_id in users_map:
            users_map[msg.from_user_id]["unread"] += 1
    return list(users_map.values())