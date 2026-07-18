from typing import Dict, Set
from fastapi import WebSocket
import asyncio
from datetime import datetime
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.pending_messages: Dict[int, list] = {}
    
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        # отправить накопленные сообщения, если есть
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