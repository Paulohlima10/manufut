from __future__ import annotations

import asyncio
import logging
import re
import secrets
from time import time

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .config import settings
from .game import GameError, game
from .models import Participant, Room, RoomStatus
from .store import store, supabase
from .supabase_backend import SupabaseError

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RoomCreate(BaseModel):
    player_name: str = Field(min_length=2, max_length=24)
    team_name: str = Field(default="Meu Time", min_length=2, max_length=28)
    primary: str = "#6d28d9"
    secondary: str = "#fbbf24"
    team_short: str = Field(default="TIM", min_length=3, max_length=3)
    player_names: list[str] = Field(default_factory=list, max_length=4)
    player_photos: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("player_photos")
    @classmethod
    def validate_player_photos(cls, photos: list[str]) -> list[str]:
        for photo in photos:
            stored_prefix = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/public/team-media/"
            valid_source = photo.startswith("data:image/jpeg;base64,") or (
                bool(settings.supabase_url) and photo.startswith(stored_prefix)
            )
            if photo and (len(photo) > 100_000 or not valid_source):
                raise ValueError("Foto de jogador inválida")
        return photos

    @field_validator("player_names")
    @classmethod
    def validate_player_names(cls, names: list[str]) -> list[str]:
        if names and (len(names) != 4 or any(not 2 <= len(clean(name)) <= 20 for name in names)):
            raise ValueError("Informe os quatro jogadores")
        return names


def user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Autenticação necessária")
    token = authorization.removeprefix("Bearer ").strip()
    if settings.dev_auth and token.startswith("dev-"):
        return token[4:]
    raise HTTPException(401, "Token inválido")


def clean(value: str) -> str:
    return re.sub(r"[^\w À-ÿ-]", "", value).strip()


@app.exception_handler(SupabaseError)
async def supabase_error_handler(_, exc: SupabaseError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health(): return {"status": "ok", "persistence": "supabase" if supabase else "local"}


async def _persist_move(room_code: str, user_id: str, command: dict) -> None:
    if not supabase:
        return
    try:
        await supabase.save_move(room_code, user_id, command)
    except Exception:
        logger.exception("Failed to persist move for room %s", room_code)


async def persist_participant(uid: str, body: RoomCreate) -> list[str]:
    if not supabase:
        return body.player_photos
    return await supabase.persist_team(
        uid,
        clean(body.player_name),
        clean(body.team_name),
        body.team_short,
        body.primary,
        body.secondary,
        [clean(name) for name in body.player_names],
        body.player_photos,
    )


async def _background_setup_room(uid: str, body: RoomCreate, room: Room) -> None:
    """Cria o perfil antes de salvar a sala (FK host_id -> manufut_profiles)."""
    if supabase:
        try:
            await persist_participant(uid, body)
        except Exception:
            logger.exception("Falha ao persistir participante %s", uid)
    try:
        await store.save(room)
    except Exception:
        logger.exception("Falha ao persistir sala %s", room.code)


@app.put("/api/team")
async def save_team(body: RoomCreate, authorization: str | None = Header(None)):
    photos = await persist_participant(user_id(authorization), body)
    return {"player_photos": photos}


@app.post("/api/rooms")
async def create_room(body: RoomCreate, authorization: str | None = Header(None)):
    uid = user_id(authorization)
    for _ in range(5):
        code = secrets.token_hex(3).upper()
        if not await store.get(code):
            break
    else:
        raise HTTPException(503, "Não foi possível gerar código de sala")
    photos = body.player_photos
    p = Participant(uid, clean(body.player_name), clean(body.team_name), body.primary, body.secondary, photos)
    room = Room(code, uid, participants={uid: p})
    await store.cache_only(room)
    asyncio.create_task(_background_setup_room(uid, body, room))
    return room.public()


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: RoomCreate, authorization: str | None = Header(None)):
    uid, room = user_id(authorization), await store.get(code)
    if not room: raise HTTPException(404, "Sala não encontrada")
    if room.status in (RoomStatus.FINISHED, RoomStatus.EXPIRED):
        raise HTTPException(410, "Sala encerrada")
    if len(room.participants) >= 2 and uid not in room.participants: raise HTTPException(409, "Sala cheia")
    photos = body.player_photos
    room.participants[uid] = Participant(uid, clean(body.player_name), clean(body.team_name), body.primary, body.secondary, photos)
    if room.status == RoomStatus.WAITING:
        room.status = RoomStatus.CONFIGURING
    await store.cache_only(room)
    asyncio.create_task(_background_setup_room(uid, body, room))
    await store.broadcast(room.code, {"type": "state", "room": room.public()})
    return room.public()


@app.get("/api/history")
async def history(authorization: str | None = Header(None)):
    return [room.public() for room in await store.history(user_id(authorization))]


@app.get("/api/rooms/{code}")
async def get_room(code: str, authorization: str | None = Header(None)):
    uid, room = user_id(authorization), await store.get(code)
    if not room or uid not in room.participants: raise HTTPException(404, "Sala não encontrada")
    return room.public()


async def _handle_ws_disconnect(room: Room, uid: str, ws: WebSocket) -> None:
    if not store.disconnect(room.code, uid, ws):
        return
    if uid not in room.participants:
        return
    room.participants[uid].connected = False
    if room.status == RoomStatus.PLAYING:
        room.status = RoomStatus.PAUSED
        game.snapshot(room, "disconnect")
    await store.save(room)
    await store.broadcast(room.code, {"type": "state", "room": room.public()})


@app.websocket("/ws/{code}")
async def websocket_endpoint(ws: WebSocket, code: str, token: str):
    try: uid = user_id(f"Bearer {token}")
    except HTTPException: await ws.close(4401); return
    room = await store.get(code)
    if not room or uid not in room.participants: await ws.close(4404); return
    await ws.accept()
    await store.connect(room.code, uid, ws)
    room.participants[uid].connected = True
    if room.status == RoomStatus.PAUSED: room.status = RoomStatus.PLAYING
    await store.broadcast(room.code, {"type": "state", "room": room.public()})
    background_tasks: set[asyncio.Task] = set()
    try:
        while True:
            try:
                data = await ws.receive_json()
            except RuntimeError:
                break
            action = data.get("type")
            try:
                if room.status == RoomStatus.PLAYING and room.match and game.expire_turn_if_needed(room):
                    await store.save(room)
                    await store.broadcast(room.code, {"type": "state", "room": room.public()})
                if action == "ready":
                    room.participants[uid].ready = bool(data.get("ready", True))
                    if len(room.participants) == 2 and all(p.ready for p in room.participants.values()): game.start(room)
                elif action == "move":
                    result = game.move(room, uid, data.get("piece_id", ""), data.get("direction", {}), float(data.get("force", 0)), int(data.get("sequence", 0)))
                    if supabase and not result.get("duplicate"):
                        move_payload = {
                            "piece_id": data.get("piece_id", ""),
                            "direction": data.get("direction", {}),
                            "force": float(data.get("force", 0)),
                            "sequence": int(data.get("sequence", 0)),
                        }
                        task = asyncio.create_task(_persist_move(room.code, uid, move_payload))
                        background_tasks.add(task)
                        task.add_done_callback(background_tasks.discard)
                elif action == "forfeit":
                    if uid not in room.participants:
                        raise GameError("Participante inválido")
                    game.finish(room, uid)
                elif action == "rematch":
                    room.participants[uid].ready = False; room.match = None; room.processed_commands.clear(); room.status = RoomStatus.CONFIGURING
                elif action == "expire_turn":
                    continue
                elif action == "ping":
                    room.participants[uid].last_seen = time(); await ws.send_json({"type": "pong"}); continue
                else: raise GameError("Comando desconhecido")
                task = asyncio.create_task(store.save(room))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
                await store.broadcast(room.code, {"type": "state", "room": room.public()})
            except (GameError, ValueError) as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        await _handle_ws_disconnect(room, uid, ws)
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
