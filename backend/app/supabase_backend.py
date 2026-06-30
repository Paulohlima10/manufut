from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from hashlib import sha256
import logging
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

logger = logging.getLogger(__name__)


class SupabaseError(RuntimeError):
    pass


class SupabaseBackend:
    def __init__(self, url: str, service_role_key: str) -> None:
        self.url = url.rstrip("/")
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(method, f"{self.url}{path}", headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise SupabaseError(f"Falha ao conectar no Supabase: {exc}") from exc
        if response.is_error:
            detail = response.text[:300]
            raise SupabaseError(f"Supabase {method} {path} retornou {response.status_code}: {detail}")
        return response

    async def upsert(self, table: str, rows: dict | list[dict], conflict: str) -> None:
        await self._request(
            "POST",
            f"/rest/v1/{table}",
            params={"on_conflict": conflict},
            headers={"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"},
            json=rows,
        )

    async def delete(self, table: str, **filters: str) -> None:
        await self._request("DELETE", f"/rest/v1/{table}", params=filters)

    async def select(self, table: str, params: dict[str, str]) -> list[dict]:
        response = await self._request("GET", f"/rest/v1/{table}", params=params)
        return response.json()

    async def upload_photo(self, user_id: str, data_url: str) -> tuple[str, str]:
        if not user_id or "/" in user_id or ".." in user_id:
            raise SupabaseError("Identificador de usuário inválido")
        encoded = data_url.partition(",")[2]
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise SupabaseError("Imagem Base64 inválida") from exc
        if not content:
            raise SupabaseError("Imagem vazia")
        digest = sha256(content).hexdigest()
        object_path = f"{user_id}/{digest}.jpg"
        await self._request(
            "POST",
            f"/storage/v1/object/team-media/{quote(object_path, safe='/')}",
            headers={"Content-Type": "image/jpeg", "x-upsert": "true"},
            content=content,
        )
        public_url = f"{self.url}/storage/v1/object/public/team-media/{quote(object_path, safe='/')}"
        return object_path, public_url

    def stored_photo(self, url: str) -> tuple[str, str] | None:
        prefix = f"{self.url}/storage/v1/object/public/team-media/"
        if not url.startswith(prefix):
            return None
        return url.removeprefix(prefix), url

    async def persist_team(
        self,
        user_id: str,
        player_name: str,
        team_name: str,
        team_short: str,
        primary: str,
        secondary: str,
        player_names: list[str],
        player_photos: list[str],
    ) -> list[str]:
        team_id = str(uuid5(NAMESPACE_URL, f"manufut:team:{user_id}"))
        await self.upsert(
            "manufut_profiles",
            {"user_id": user_id, "display_name": player_name, "updated_at": _now()},
            "user_id",
        )
        await self.upsert(
            "manufut_teams",
            {
                "id": team_id,
                "owner_id": user_id,
                "name": team_name,
                "short_name": (team_short or team_name[:3]).upper()[:3].ljust(3, "X"),
                "primary_color": primary,
                "secondary_color": secondary,
                "updated_at": _now(),
            },
            "id",
        )
        upload_tasks: list[asyncio.Task[tuple[str | None, str]]] = []
        for index, photo in enumerate(player_photos[:4]):
            if not photo:
                continue
            stored = self.stored_photo(photo)
            if stored:
                path, url = stored
                upload_tasks.append(asyncio.create_task(asyncio.sleep(0, result=(path, url))))
            else:
                upload_tasks.append(asyncio.create_task(self.upload_photo(user_id, photo)))
        uploaded = await asyncio.gather(*upload_tasks, return_exceptions=True)
        photo_paths: list[str | None] = [None] * 4
        photo_urls: list[str] = [""] * 4
        for index, (task, photo) in enumerate(zip(upload_tasks, player_photos[:4])):
            if not photo:
                continue
            result = uploaded[index]
            if isinstance(result, BaseException):
                logger.warning("Falha ao enviar foto %d do jogador %s: %s", index, user_id, result)
                continue
            path, url = result
            photo_paths[index] = path
            photo_urls[index] = url

        players = []
        names = (player_names + ["Jogador 1", "Jogador 2", "Jogador 3", "Goleiro"])[:4]
        for position, name in enumerate(names):
            players.append(
                {
                    "team_id": team_id,
                    "position": position,
                    "name": name,
                    "role": "goalkeeper" if position == 3 else "line",
                    "photo_path": photo_paths[position],
                }
            )
        await self.upsert("manufut_players", players, "team_id,position")
        return photo_urls

    async def get_room(self, code: str) -> dict | None:
        rows = await self.select(
            "manufut_rooms",
            {"code": f"eq.{code.upper()}", "select": "state", "limit": "1"},
        )
        return rows[0]["state"] if rows else None

    async def save_room(self, state: dict) -> None:
        room = {
            "code": state["code"],
            "host_id": state["host_id"],
            "status": state["status"],
            "participant_ids": list(state["participants"]),
            "state": state,
            "last_activity": _from_epoch(state["last_activity"]),
        }
        await self.upsert("manufut_rooms", room, "code")
        match = state.get("match")
        if match:
            await self.upsert(
                "manufut_matches",
                {
                    "room_code": state["code"],
                    "status": state["status"],
                    "participant_ids": list(state["participants"]),
                    "score": match.get("score", {}),
                    "winner_id": match.get("winner_id"),
                    "state": match,
                    "started_at": _from_epoch(match["started_at"]),
                    "ended_at": _now() if state["status"] == "finished" else None,
                    "updated_at": _now(),
                },
                "room_code",
            )
        snapshots = [
            {
                "room_code": state["code"],
                "snapshot_index": index,
                "reason": snapshot["reason"],
                "state": snapshot.get("state"),
                "created_at": _from_epoch(snapshot["created_at"]),
            }
            for index, snapshot in enumerate(state.get("snapshots", []))
        ]
        if snapshots:
            await self.upsert("manufut_snapshots", snapshots, "room_code,snapshot_index")

    async def delete_room(self, code: str) -> None:
        await self.delete("manufut_rooms", code=f"eq.{code.upper()}")

    async def save_move(self, room_code: str, user_id: str, command: dict) -> None:
        await self.upsert(
            "manufut_moves",
            {
                "room_code": room_code,
                "user_id": user_id,
                "sequence": int(command["sequence"]),
                "command": command,
            },
            "room_code,user_id,sequence",
        )

    async def history(self, user_id: str) -> list[dict]:
        rows = await self.select(
            "manufut_rooms",
            {
                "participant_ids": f"cs.{{{user_id}}}",
                "status": "eq.finished",
                "select": "state",
                "order": "last_activity.desc",
                "limit": "20",
            },
        )
        return [row["state"] for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()
