from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any


class RoomStatus(str, Enum):
    WAITING = "waiting"
    CONFIGURING = "configuring"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"
    EXPIRED = "expired"


@dataclass
class Vec:
    x: float
    y: float


@dataclass
class Piece:
    id: str
    owner_id: str
    role: str
    position: Vec
    velocity: Vec = field(default_factory=lambda: Vec(0, 0))
    radius: float = 22


@dataclass
class Participant:
    id: str
    name: str
    team_name: str = "Meu Time"
    primary: str = "#6d28d9"
    secondary: str = "#fbbf24"
    player_photos: list[str] = field(default_factory=list)
    ready: bool = False
    connected: bool = True
    last_seen: float = field(default_factory=time)


@dataclass
class MatchState:
    pieces: list[Piece]
    ball: Piece
    turn_player_id: str
    score: dict[str, int]
    sequence: int = 0
    turns_left: int = 20
    started_at: float = field(default_factory=time)
    turn_deadline: float = 0
    winner_id: str | None = None
    last_move: dict[str, Any] | None = None


@dataclass
class Room:
    code: str
    host_id: str
    status: RoomStatus = RoomStatus.WAITING
    participants: dict[str, Participant] = field(default_factory=dict)
    match: MatchState | None = None
    processed_commands: set[str] = field(default_factory=set)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time)
    last_activity: float = field(default_factory=time)
    paused_at: float | None = None

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("processed_commands", None)
        data["status"] = self.status.value
        return data
