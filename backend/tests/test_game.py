from backend.app.game import GameError, game
from backend.app.models import Participant, Room, RoomStatus


def room():
    r = Room("ABC123", "a", participants={"a": Participant("a", "Ana", ready=True), "b": Participant("b", "Bia", ready=True)})
    game.start(r)
    return r


def test_start_and_turn_change():
    r = room(); piece = next(p for p in r.match.pieces if p.owner_id == "a")
    game.move(r, "a", piece.id, {"x": 1, "y": 0}, .5, 1)
    assert r.match.turn_player_id == "b" and len(r.snapshots) == 2


def test_rejects_force_and_wrong_turn():
    r = room(); piece = next(p for p in r.match.pieces if p.owner_id == "a")
    for player, force in [("b", .5), ("a", 2)]:
        try: game.move(r, player, piece.id, {"x": 1, "y": 0}, force, 1)
        except GameError: pass
        else: assert False


def test_duplicate_is_idempotent():
    r = room(); piece = next(p for p in r.match.pieces if p.owner_id == "a")
    game.move(r, "a", piece.id, {"x": 1, "y": 0}, .5, 1)
    assert game.move(r, "a", piece.id, {"x": 1, "y": 0}, .5, 1)["duplicate"]
