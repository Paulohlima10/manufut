import asyncio
from pathlib import Path
from types import SimpleNamespace

from backend.app.game import game
from backend.app.models import Participant, Room
from backend.app.store import JsonRoomStateStore
from backend.app.store import SupabaseRoomStateStore
from backend.app.store import _build_store


def test_room_survives_store_restart(tmp_path: Path):
    path = tmp_path / "rooms.json"
    room = Room(
        "EC46DA",
        "host",
        participants={
            "host": Participant("host", "Ana", ready=True),
            "guest": Participant("guest", "Bia", ready=True),
        },
    )
    game.start(room)
    room.processed_commands.add("host:1")

    asyncio.run(JsonRoomStateStore(path).save(room))
    restored = asyncio.run(JsonRoomStateStore(path).get("ec46da"))

    assert restored is not None
    assert restored.code == "EC46DA"
    assert restored.participants["host"].name == "Ana"
    assert restored.match is not None
    assert restored.match.ball.position.x == 500
    assert restored.processed_commands == {"host:1"}


class FakeSupabaseBackend:
    def __init__(self, state):
        self.state = state
        self.reads = 0

    async def get_room(self, _):
        self.reads += 1
        return self.state


def test_supabase_store_reuses_active_room_instance():
    room = Room("ABC123", "host", participants={"host": Participant("host", "Ana")})
    from backend.app.store import _room_to_dict

    backend = FakeSupabaseBackend(_room_to_dict(room))
    store = SupabaseRoomStateStore(backend)
    first = asyncio.run(store.get("ABC123"))
    second = asyncio.run(store.get("abc123"))

    assert first is second
    assert backend.reads == 1


def test_invalid_supabase_host_falls_back_to_local_store(monkeypatch, tmp_path: Path):
    config = SimpleNamespace(
        supabase_url="https://invalid-project.supabase.co",
        supabase_service_role_key="secret",
        room_store_path=tmp_path / "rooms.json",
    )

    def fake_getaddrinfo(*_args, **_kwargs):
        raise OSError("dns failure")

    monkeypatch.setattr("backend.app.store.socket.getaddrinfo", fake_getaddrinfo)

    backend, store = _build_store(config)

    assert backend is None
    assert isinstance(store, JsonRoomStateStore)
