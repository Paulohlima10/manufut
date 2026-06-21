from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Lock
from time import time

from fastapi import WebSocket

from .models import Room


class RoomStateStore(ABC):
    @abstractmethod
    async def get(self, code: str) -> Room | None: ...

    @abstractmethod
    async def save(self, room: Room) -> None: ...

    @abstractmethod
    async def delete(self, code: str) -> None: ...


class InMemoryRoomStateStore(RoomStateStore):
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.lock = Lock()

    async def get(self, code: str) -> Room | None:
        return self.rooms.get(code.upper())

    async def save(self, room: Room) -> None:
        room.last_activity = time()
        async with self.lock:
            self.rooms[room.code] = room

    async def delete(self, code: str) -> None:
        async with self.lock:
            self.rooms.pop(code.upper(), None)
            self.connections.pop(code.upper(), None)

    def connect(self, code: str, user_id: str, ws: WebSocket) -> None:
        self.connections.setdefault(code, {})[user_id] = ws

    def disconnect(self, code: str, user_id: str) -> None:
        self.connections.get(code, {}).pop(user_id, None)

    async def broadcast(self, code: str, payload: dict) -> None:
        stale: list[str] = []
        for user_id, ws in list(self.connections.get(code, {}).items()):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(user_id)
        for user_id in stale:
            self.disconnect(code, user_id)


store = InMemoryRoomStateStore()

