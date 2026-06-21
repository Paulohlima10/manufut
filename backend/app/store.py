from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from asyncio import Lock
from dataclasses import asdict
import json
import logging
from pathlib import Path
from time import time

from fastapi import WebSocket

from .config import settings
from .models import MatchState, Participant, Piece, Room, RoomStatus, Vec
from .supabase_backend import SupabaseBackend


logger = logging.getLogger(__name__)


class RoomStateStore(ABC):
    @abstractmethod
    async def get(self, code: str) -> Room | None: ...

    @abstractmethod
    async def save(self, room: Room) -> None: ...

    @abstractmethod
    async def delete(self, code: str) -> None: ...

    @abstractmethod
    async def history(self, user_id: str) -> list[Room]: ...

    async def cache_only(self, room: Room) -> None:
        """Atualiza somente o cache em memória (sem agendar persistência)."""
        room.last_activity = time()
        async with self.lock:
            self.rooms[room.code] = room


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

    async def history(self, user_id: str) -> list[Room]:
        rooms = [room for room in self.rooms.values() if room.status == RoomStatus.FINISHED and user_id in room.participants]
        return sorted(rooms, key=lambda room: room.last_activity, reverse=True)[:20]

    async def connect(self, code: str, user_id: str, ws: WebSocket) -> None:
        room_connections = self.connections.setdefault(code, {})
        old_ws = room_connections.get(user_id)
        room_connections[user_id] = ws
        if old_ws is not None and old_ws is not ws:
            try:
                await old_ws.close(4000, "Replaced by new connection")
            except Exception:
                pass

    def disconnect(self, code: str, user_id: str, ws: WebSocket | None = None) -> bool:
        room_connections = self.connections.get(code, {})
        if ws is not None and room_connections.get(user_id) is not ws:
            return False
        room_connections.pop(user_id, None)
        return True

    async def broadcast(self, code: str, payload: dict) -> None:
        stale: list[str] = []
        for user_id, ws in list(self.connections.get(code, {}).items()):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(user_id)
        for user_id in stale:
            self.disconnect(code, user_id)


def _piece_from_dict(data: dict) -> Piece:
    return Piece(
        id=data["id"],
        owner_id=data["owner_id"],
        role=data["role"],
        position=Vec(**data["position"]),
        velocity=Vec(**data.get("velocity", {"x": 0, "y": 0})),
        radius=data.get("radius", 22),
    )


def _room_from_dict(data: dict) -> Room:
    match_data = data.get("match")
    match = None
    if match_data:
        match = MatchState(
            pieces=[_piece_from_dict(piece) for piece in match_data["pieces"]],
            ball=_piece_from_dict(match_data["ball"]),
            turn_player_id=match_data["turn_player_id"],
            score=match_data["score"],
            sequence=match_data.get("sequence", 0),
            turns_left=match_data.get("turns_left", settings.match_turns),
            started_at=match_data.get("started_at", time()),
            turn_deadline=match_data.get("turn_deadline", 0),
            winner_id=match_data.get("winner_id"),
            last_move=match_data.get("last_move"),
        )
    return Room(
        code=data["code"],
        host_id=data["host_id"],
        status=RoomStatus(data.get("status", RoomStatus.WAITING)),
        participants={key: Participant(**value) for key, value in data.get("participants", {}).items()},
        match=match,
        processed_commands=set(data.get("processed_commands", [])),
        snapshots=data.get("snapshots", []),
        created_at=data.get("created_at", time()),
        last_activity=data.get("last_activity", time()),
        paused_at=data.get("paused_at"),
    )


def _room_to_dict(room: Room) -> dict:
    data = asdict(room)
    data["status"] = room.status.value
    data["processed_commands"] = sorted(room.processed_commands)
    return data


class JsonRoomStateStore(InMemoryRoomStateStore):
    """Single-instance room store that survives development server reloads."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._write_lock = Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.rooms = {code: _room_from_dict(room) for code, room in data.items()}
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception("Could not load room state from %s", self.path)

    async def save(self, room: Room) -> None:
        room.last_activity = time()
        async with self.lock:
            self.rooms[room.code] = room
            snapshot = {code: _room_to_dict(r) for code, r in self.rooms.items()}
        await self._write_async(snapshot)

    async def delete(self, code: str) -> None:
        async with self.lock:
            self.rooms.pop(code.upper(), None)
            self.connections.pop(code.upper(), None)
            snapshot = {code: _room_to_dict(r) for code, r in self.rooms.items()}
        await self._write_async(snapshot)

    async def _write_async(self, snapshot: dict) -> None:
        async with self._write_lock:
            try:
                await asyncio.to_thread(self._write_payload, snapshot)
            except OSError:
                logger.exception("Could not persist room state to %s", self.path)

    def _write_payload(self, snapshot: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=True), encoding="utf-8")
        temporary.replace(self.path)


class SupabaseRoomStateStore(InMemoryRoomStateStore):
    def __init__(self, backend: SupabaseBackend) -> None:
        super().__init__()
        self.backend = backend

    async def get(self, code: str) -> Room | None:
        cached = self.rooms.get(code.upper())
        if cached:
            return cached
        data = await self.backend.get_room(code)
        if not data:
            return None
        room = _room_from_dict(data)
        self.rooms[room.code] = room
        return room

    async def save(self, room: Room) -> None:
        room.last_activity = time()
        async with self.lock:
            self.rooms[room.code] = room
        try:
            await self.backend.save_room(_room_to_dict(room))
        except Exception:
            logger.exception("Falha ao persistir sala %s", room.code)

    async def delete(self, code: str) -> None:
        async with self.lock:
            self.rooms.pop(code.upper(), None)
            self.connections.pop(code.upper(), None)
        try:
            await self.backend.delete_room(code)
        except Exception:
            logger.exception("Falha ao remover sala %s", code)

    async def history(self, user_id: str) -> list[Room]:
        return [_room_from_dict(data) for data in await self.backend.history(user_id)]


supabase = None
if settings.supabase_url and settings.supabase_service_role_key:
    supabase = SupabaseBackend(settings.supabase_url, settings.supabase_service_role_key)
    store: RoomStateStore = SupabaseRoomStateStore(supabase)
else:
    store = JsonRoomStateStore(settings.room_store_path)
