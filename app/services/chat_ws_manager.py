import json
import logging
from typing import Dict, Set, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ChatWebSocketManager:
    """
    Manages active WebSocket connections for real-time messaging
    across conversations and individual users.
    """
    def __init__(self):
        # conversation_id -> set of WebSockets
        self.conversation_rooms: Dict[str, Set[WebSocket]] = {}
        # user_id -> set of WebSockets
        self.user_rooms: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, conversation_id: str, user_id: str):
        await websocket.accept()
        
        # Add to conversation room
        if conversation_id not in self.conversation_rooms:
            self.conversation_rooms[conversation_id] = set()
        self.conversation_rooms[conversation_id].add(websocket)

        # Add to user room
        if user_id not in self.user_rooms:
            self.user_rooms[user_id] = set()
        self.user_rooms[user_id].add(websocket)

        logger.info(f"WebSocket connected: user={user_id}, conv={conversation_id}")

    def disconnect(self, websocket: WebSocket, conversation_id: str, user_id: str):
        # Remove from conversation room
        if conversation_id in self.conversation_rooms:
            self.conversation_rooms[conversation_id].discard(websocket)
            if not self.conversation_rooms[conversation_id]:
                del self.conversation_rooms[conversation_id]

        # Remove from user room
        if user_id in self.user_rooms:
            self.user_rooms[user_id].discard(websocket)
            if not self.user_rooms[user_id]:
                del self.user_rooms[user_id]

        logger.info(f"WebSocket disconnected: user={user_id}, conv={conversation_id}")

    async def broadcast_to_conversation(self, conversation_id: str, data: Dict[str, Any]):
        """Broadcasts a payload to all connected clients in a conversation."""
        if conversation_id not in self.conversation_rooms:
            return

        dead_sockets = set()
        message_str = json.dumps(data, default=str)
        for ws in list(self.conversation_rooms[conversation_id]):
            try:
                await ws.send_text(message_str)
            except Exception as e:
                logger.warning(f"Error broadcasting to WebSocket: {e}")
                dead_sockets.add(ws)

        for ws in dead_sockets:
            self.conversation_rooms[conversation_id].discard(ws)

    async def send_to_user(self, user_id: str, data: Dict[str, Any]):
        """Sends a direct notification/update to a specific user across any active connections."""
        if user_id not in self.user_rooms:
            return

        dead_sockets = set()
        message_str = json.dumps(data, default=str)
        for ws in list(self.user_rooms[user_id]):
            try:
                await ws.send_text(message_str)
            except Exception as e:
                logger.warning(f"Error sending direct to WebSocket: {e}")
                dead_sockets.add(ws)

        for ws in dead_sockets:
            self.user_rooms[user_id].discard(ws)

chat_ws_manager = ChatWebSocketManager()
