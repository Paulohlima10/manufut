from __future__ import annotations

import re
import secrets
from time import time

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .game import GameError, game
from .models import Participant, Room, RoomStatus
from .store import store

app = FastAPI(title=settings.app_name)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class RoomCreate(BaseModel):
    player_name: str = Field(min_length=2, max_length=24)
    team_name: str = Field(default="Meu Time", min_length=2, max_length=28)
    primary: str = "#6d28d9"
    secondary: str = "#fbbf24"


def user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Autenticação necessária")
    token = authorization.removeprefix("Bearer ").strip()
    if settings.dev_auth and token.startswith("dev-"):
        return token[4:]
    raise HTTPException(401, "Token inválido")


def clean(value: str) -> str:
    return re.sub(r"[^\w À-ÿ-]", "", value).strip()


@app.get("/health")
def health(): return {"status": "ok"}


@app.post("/api/rooms")
async def create_room(body: RoomCreate, authorization: str | None = Header(None)):
    uid = user_id(authorization)
    code = secrets.token_hex(3).upper()
    p = Participant(uid, clean(body.player_name), clean(body.team_name), body.primary, body.secondary)
    room = Room(code, uid, participants={uid: p})
    await store.save(room)
    return room.public()


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: RoomCreate, authorization: str | None = Header(None)):
    uid, room = user_id(authorization), await store.get(code)
    if not room: raise HTTPException(404, "Sala não encontrada")
    if len(room.participants) >= 2 and uid not in room.participants: raise HTTPException(409, "Sala cheia")
    room.participants[uid] = Participant(uid, clean(body.player_name), clean(body.team_name), body.primary, body.secondary)
    room.status = RoomStatus.CONFIGURING
    await store.save(room)
    await store.broadcast(room.code, {"type": "state", "room": room.public()})
    return room.public()


@app.get("/api/rooms/{code}")
async def get_room(code: str, authorization: str | None = Header(None)):
    uid, room = user_id(authorization), await store.get(code)
    if not room or uid not in room.participants: raise HTTPException(404, "Sala não encontrada")
    return room.public()


@app.websocket("/ws/{code}")
async def websocket_endpoint(ws: WebSocket, code: str, token: str):
    try: uid = user_id(f"Bearer {token}")
    except HTTPException: await ws.close(4401); return
    room = await store.get(code)
    if not room or uid not in room.participants: await ws.close(4404); return
    await ws.accept(); store.connect(room.code, uid, ws)
    room.participants[uid].connected = True
    if room.status == RoomStatus.PAUSED: room.status = RoomStatus.PLAYING
    await store.broadcast(room.code, {"type": "state", "room": room.public()})
    try:
        while True:
            data = await ws.receive_json(); action = data.get("type")
            try:
                if action == "ready":
                    room.participants[uid].ready = bool(data.get("ready", True))
                    if len(room.participants) == 2 and all(p.ready for p in room.participants.values()): game.start(room)
                elif action == "move":
                    game.move(room, uid, data.get("piece_id", ""), data.get("direction", {}), float(data.get("force", 0)), int(data.get("sequence", 0)))
                elif action == "forfeit": game.finish(room, uid)
                elif action == "rematch":
                    room.participants[uid].ready = False; room.match = None; room.processed_commands.clear(); room.status = RoomStatus.CONFIGURING
                elif action == "ping":
                    room.participants[uid].last_seen = time(); await ws.send_json({"type": "pong"}); continue
                else: raise GameError("Comando desconhecido")
                await store.save(room)
                await store.broadcast(room.code, {"type": "state", "room": room.public()})
            except (GameError, ValueError) as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        store.disconnect(room.code, uid); room.participants[uid].connected = False
        if room.status == RoomStatus.PLAYING:
            room.status = RoomStatus.PAUSED; game.snapshot(room, "disconnect")
        await store.save(room); await store.broadcast(room.code, {"type": "state", "room": room.public()})

