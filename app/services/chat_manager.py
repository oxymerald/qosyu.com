"""Управление активными WebSocket-соединениями чата (в рамках одного процесса)."""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int, websocket: WebSocket | None = None):
        current = self.active_connections.get(user_id)
        if current is not None and (websocket is None or current is websocket):
            self.active_connections.pop(user_id, None)

    async def send_message(self, user_id: int, message: dict) -> bool:
        websocket = self.active_connections.get(user_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            self.disconnect(user_id, websocket)
            return False


manager = ConnectionManager()
