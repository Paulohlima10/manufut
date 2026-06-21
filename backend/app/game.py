from __future__ import annotations

import math
from dataclasses import asdict
from time import time

from .config import settings
from .models import MatchState, Participant, Piece, Room, RoomStatus, Vec

FIELD_W, FIELD_H = 1000.0, 600.0
GOAL_Y1, GOAL_Y2 = 220.0, 380.0
MAX_PROCESSED_COMMANDS = 1024
MAX_SNAPSHOTS = 64


class GameError(ValueError):
    pass


class GameService:
    def _other_player(self, room: Room, player_id: str) -> str:
        ids = list(room.participants)
        if len(ids) != 2:
            raise GameError("Partida inválida")
        return ids[1] if player_id == ids[0] else ids[0]

    def _end_turn(self, room: Room, next_player_id: str) -> None:
        match = room.match
        if not match or room.status != RoomStatus.PLAYING:
            return
        match.turn_player_id = next_player_id
        match.turns_left -= 1
        match.turn_deadline = time() + settings.turn_seconds
        if match.turns_left <= 0:
            self.finish(room)

    def resume_from_pause(self, room: Room) -> None:
        if room.status != RoomStatus.PAUSED or not room.paused_at or not room.match:
            return
        room.match.turn_deadline += time() - room.paused_at
        room.paused_at = None
        room.status = RoomStatus.PLAYING

    def _formation_positions(self, room: Room) -> dict[str, Vec]:
        positions: dict[str, Vec] = {}
        ys = [190.0, 300.0, 410.0]
        for side, player_id in enumerate(room.participants):
            x = 255.0 if side == 0 else 745.0
            for i, y in enumerate(ys):
                positions[f"{player_id}-p{i}"] = Vec(x, y)
            positions[f"{player_id}-gk"] = Vec(78.0 if side == 0 else 922.0, 300.0)
        return positions

    def start(self, room: Room) -> None:
        players = list(room.participants.values())
        if len(players) != 2 or not all(p.ready for p in players):
            raise GameError("Os dois jogadores precisam estar prontos")
        formation = self._formation_positions(room)
        pieces: list[Piece] = []
        for player_id in room.participants:
            for i in range(3):
                pieces.append(Piece(f"{player_id}-p{i}", player_id, "line", formation[f"{player_id}-p{i}"]))
            pieces.append(Piece(f"{player_id}-gk", player_id, "goalkeeper", formation[f"{player_id}-gk"], radius=25))
        room.match = MatchState(
            pieces,
            Piece("ball", "", "ball", Vec(500, 300), radius=13),
            players[0].id,
            {p.id: 0 for p in players},
            turns_left=settings.match_turns,
            turn_deadline=time() + settings.turn_seconds,
        )
        room.status = RoomStatus.PLAYING
        room.processed_commands.clear()
        room.snapshots.clear()
        self.snapshot(room, "match_started")

    def expire_turn_if_needed(self, room: Room) -> bool:
        match = room.match
        if not match or room.status != RoomStatus.PLAYING:
            return False
        if time() <= match.turn_deadline:
            return False
        self._skip_turn(room)
        return True

    def move(self, room: Room, player_id: str, piece_id: str, direction: dict, force: float, sequence: int) -> dict:
        match = room.match
        if room.status != RoomStatus.PLAYING or not match:
            raise GameError("A partida não está em andamento")
        self.expire_turn_if_needed(room)
        match = room.match
        assert match
        command_id = f"{player_id}:{sequence}"
        if command_id in room.processed_commands:
            return {"duplicate": True}
        if match.turn_player_id != player_id:
            raise GameError("Não é o seu turno")
        if sequence != match.sequence + 1:
            raise GameError("Sequência inválida")
        if not 0 < force <= settings.max_force:
            raise GameError("Força inválida")
        piece = next((p for p in match.pieces if p.id == piece_id), None)
        if not piece or piece.owner_id != player_id:
            raise GameError("Peça inválida")
        dx, dy = float(direction.get("x", 0)), float(direction.get("y", 0))
        length = math.hypot(dx, dy)
        if length < .01:
            raise GameError("Direção inválida")
        room.processed_commands.add(command_id)
        self._trim_processed_commands(room)
        match.sequence = sequence
        initial = {p.id: {"x": p.position.x, "y": p.position.y} for p in match.pieces}
        initial["ball"] = {"x": match.ball.position.x, "y": match.ball.position.y}
        match.last_move = {
            "piece_id": piece_id,
            "direction": {"x": dx, "y": dy},
            "force": force,
            "initial": initial,
        }
        piece.velocity = Vec(dx / length * force * 25, dy / length * force * 25)
        goal = self._simulate(match)
        if goal:
            match.score[goal] += 1
            self._reset_positions(room)
        next_player = self._other_player(room, goal if goal else player_id)
        self._end_turn(room, next_player)
        self.snapshot(room, "goal" if goal else "move")
        self._trim_snapshots(room)
        return {"duplicate": False, "goal": goal}

    def _skip_turn(self, room: Room) -> None:
        match = room.match
        if not match or room.status != RoomStatus.PLAYING:
            return
        if match.turn_player_id not in room.participants:
            return
        self._end_turn(room, self._other_player(room, match.turn_player_id))
        self.snapshot(room, "turn_timeout")
        self._trim_snapshots(room)

    def _trim_processed_commands(self, room: Room) -> None:
        if len(room.processed_commands) <= MAX_PROCESSED_COMMANDS:
            return
        keep = sorted(room.processed_commands)[-MAX_PROCESSED_COMMANDS:]
        room.processed_commands = set(keep)

    def _trim_snapshots(self, room: Room) -> None:
        if len(room.snapshots) > MAX_SNAPSHOTS:
            room.snapshots = room.snapshots[-MAX_SNAPSHOTS:]

    def _simulate(self, match: MatchState) -> str | None:
        bodies = match.pieces + [match.ball]
        score_ids = list(match.score)
        for _ in range(360):
            moving = False
            for body in bodies:
                body.position.x += body.velocity.x
                body.position.y += body.velocity.y
                body.velocity.x *= .965
                body.velocity.y *= .965
                if math.hypot(body.velocity.x, body.velocity.y) > .06:
                    moving = True
                else:
                    body.velocity = Vec(0, 0)
                if body is match.ball and GOAL_Y1 < body.position.y < GOAL_Y2:
                    if body.position.x < -body.radius:
                        return score_ids[1] if len(score_ids) > 1 else score_ids[0]
                    if body.position.x > FIELD_W + body.radius:
                        return score_ids[0]
                if body.position.y < body.radius or body.position.y > FIELD_H - body.radius:
                    body.position.y = max(body.radius, min(FIELD_H-body.radius, body.position.y)); body.velocity.y *= -.72
                if body.position.x < body.radius or body.position.x > FIELD_W-body.radius:
                    if body is match.ball and GOAL_Y1 < body.position.y < GOAL_Y2:
                        pass
                    else:
                        body.position.x = max(body.radius, min(FIELD_W-body.radius, body.position.x)); body.velocity.x *= -.72
            for i, a in enumerate(bodies):
                for b in bodies[i+1:]:
                    dx, dy = b.position.x-a.position.x, b.position.y-a.position.y
                    dist, minimum = math.hypot(dx, dy), a.radius+b.radius
                    if 0 < dist < minimum:
                        nx, ny = dx/dist, dy/dist
                        overlap = (minimum-dist)/2
                        a.position.x -= nx*overlap; a.position.y -= ny*overlap
                        b.position.x += nx*overlap; b.position.y += ny*overlap
                        impulse = (a.velocity.x-b.velocity.x)*nx + (a.velocity.y-b.velocity.y)*ny
                        if impulse > 0:
                            a.velocity.x -= impulse*nx; a.velocity.y -= impulse*ny
                            b.velocity.x += impulse*nx; b.velocity.y += impulse*ny
            if not moving:
                break
        return None

    def _reset_positions(self, room: Room) -> None:
        assert room.match
        formation = self._formation_positions(room)
        for piece in room.match.pieces:
            piece.position = formation[piece.id]
            piece.velocity = Vec(0, 0)
        room.match.ball.position = Vec(500, 300)
        room.match.ball.velocity = Vec(0, 0)

    def finish(self, room: Room, forfeiter: str | None = None) -> None:
        assert room.match
        if forfeiter:
            opponents = [pid for pid in room.participants if pid != forfeiter]
            if opponents:
                room.match.winner_id = opponents[0]
        else:
            scores = room.match.score
            if len(set(scores.values())) > 1:
                room.match.winner_id = max(scores, key=scores.get)
        room.status = RoomStatus.FINISHED
        self.snapshot(room, "match_finished")
        self._trim_snapshots(room)

    def snapshot(self, room: Room, reason: str) -> None:
        room.snapshots.append({"reason": reason, "created_at": time(), "state": room.public().get("match")})


game = GameService()
