import asyncio
import base64
from datetime import datetime

import httpx

from backend.app.supabase_backend import SupabaseBackend


class RecordingBackend(SupabaseBackend):
    def __init__(self):
        super().__init__("https://project.supabase.co", "secret")
        self.requests = []
        self.upserts = []

    async def _request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return httpx.Response(200, json={})

    async def upsert(self, table, rows, conflict):
        self.upserts.append((table, rows, conflict))


def test_uploads_photo_to_storage_using_content_hash():
    backend = RecordingBackend()
    content = b"jpeg-content"
    data_url = "data:image/jpeg;base64," + base64.b64encode(content).decode()

    path, url = asyncio.run(backend.upload_photo("user-1", data_url))

    assert path.startswith("user-1/") and path.endswith(".jpg")
    assert url.endswith(path)
    assert backend.requests[0][0] == "POST"
    assert backend.requests[0][2]["content"] == content
    assert backend.requests[0][2]["headers"]["x-upsert"] == "true"


def test_existing_storage_url_is_not_uploaded_again():
    backend = RecordingBackend()
    url = "https://project.supabase.co/storage/v1/object/public/team-media/user/photo.jpg"

    photos = asyncio.run(
        backend.persist_team(
            "user",
            "Ana",
            "Time Ana",
            "ANA",
            "#112233",
            "#445566",
            ["A", "B", "C", "D"],
            [url],
        )
    )

    assert photos[0] == url
    assert backend.requests == []
    assert [row[0] for row in backend.upserts] == [
        "manufut_profiles",
        "manufut_teams",
        "manufut_players",
    ]


def test_room_timestamps_are_postgres_compatible():
    backend = RecordingBackend()
    state = {
        "code": "ABC123",
        "host_id": "host",
        "status": "waiting",
        "participants": {"host": {}},
        "match": None,
        "snapshots": [],
        "last_activity": 1_700_000_000.0,
    }

    asyncio.run(backend.save_room(state))
    room = backend.upserts[0][1]

    assert datetime.fromisoformat(room["last_activity"]).tzinfo is not None


def test_move_is_idempotent_by_room_player_and_sequence():
    backend = RecordingBackend()

    asyncio.run(backend.save_move("ABC123", "host", {"sequence": 4, "force": 0.5}))

    table, row, conflict = backend.upserts[0]
    assert table == "manufut_moves"
    assert row["sequence"] == 4
    assert conflict == "room_code,user_id,sequence"
