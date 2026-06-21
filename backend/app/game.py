from __future__ import annotations

import math
from dataclasses import asdict
from time import time

from .config import settings
from .models import MatchState, Participant, Piece, Room, RoomStatus, Vec

FIELD_W, FIELD_H = 1000.0, 600.0
GOAL_Y1, GOAL_Y2 = 220.0, 380.0


class GameError(ValueError):
    pass


class GameService:
    def start(self, room: Room) -> None:
        players = list(room.participants.values())
        if len(players) != 2 or not all(p.ready for p in players):
            raise GameError("Os dois jogadores precisam estar prontos")
        pieces: list[Piece] = []
        ys = [190, 300, 410]
        for side, player in enumerate(players):
            x = 255 if side == 0 else 745
            for i, y in enumerate(ys):
                pieces.append(Piece(f"{player.id}-p{i}", player.id, "line", Vec(x, y)))
            pieces.append(Piece(f"{player.id}-gk", player.id, "goalkeeper", Vec(78 if side == 0 else 922, 300), radius=25))
        room.match = MatchState(pieces, Piece("ball", "", "ball", Vec(500, 300), radius=13), players[0].id, {p.id: 0 for p in players}, turn_deadline=time() + settings.turn_seconds)
        room.status = RoomStatus.PLAYING
        self.snapshot(room, "match_started")

    def move(self, room: Room, player_id: str, piece_id: str, direction: dict, force: float, sequence: int) -> dict:
        match = room.match
        if room.status != RoomStatus.PLAYING or not match:
            raise GameError("A partida não está em andamento")
        if match.turn_player_id != player_id:
            raise GameError("Não é o seu turno")
        command_id = f"{player_id}:{sequence}"
        if command_id in room.processed_commands:
            return {"duplicate": True}
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
        match.sequence = sequence
        piece.velocity = Vec(dx / length * force * 25, dy / length * force * 25)
        goal = self._simulate(match)
        if goal:
            match.score[goal] += 1
            self._reset_positions(room)
        match.turns_left -= 1
        ids = list(room.participants)
        match.turn_player_id = ids[1] if player_id == ids[0] else ids[0]
        match.turn_deadline = time() + settings.turn_seconds
        if match.turns_left <= 0:
            self.finish(room)
        self.snapshot(room, "goal" if goal else "move")
        return {"duplicate": False, "goal": goal}

    def _simulate(self, match: MatchState) -> str | None:
        bodies = match.pieces + [match.ball]
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
                        return list(match.score)[1]
                    if body.position.x > FIELD_W + body.radius:
                        return list(match.score)[0]
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
        room.match.ball.position = Vec(500, 300)
        room.match.ball.velocity = Vec(0, 0)

    def finish(self, room: Room, forfeiter: str | None = None) -> None:
        assert room.match
        if forfeiter:
            room.match.winner_id = next(pid for pid in room.participants if pid != forfeiter)
        else:
            scores = room.match.score
            if len(set(scores.values())) > 1:
                room.match.winner_id = max(scores, key=scores.get)
        room.status = RoomStatus.FINISHED
        self.snapshot(room, "match_finished")

    def snapshot(self, room: Room, reason: str) -> None:
        room.snapshots.append({"reason": reason, "created_at": time(), "state": room.public().get("match")})


game = GameService()

