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


def test_turn_alternates_over_multiple_moves():
    r = room()
    for _ in range(4):
        current = r.match.turn_player_id
        piece = next(p for p in r.match.pieces if p.owner_id == current)
        seq = r.match.sequence + 1
        game.move(r, current, piece.id, {"x": 1, "y": 0}, 0.5, seq)
        assert r.match.turn_player_id != current


def test_expire_turn_skips_to_opponent():
    r = room()
    assert r.match.turn_player_id == "a"
    r.match.turn_deadline = 0
    assert game.expire_turn_if_needed(r)
    assert r.match.turn_player_id == "b"
    assert not game.expire_turn_if_needed(r)


def test_move_expires_before_validating_turn():
    r = room()
    r.match.turn_deadline = 0
    piece = next(p for p in r.match.pieces if p.owner_id == "b")
    game.move(r, "b", piece.id, {"x": 1, "y": 0}, 0.5, 1)
    assert r.match.turn_player_id == "a"
    assert r.match.sequence == 1


def test_goal_resets_formation():
    from backend.app.models import Vec

    r = room()
    r.match.ball.position = Vec(980, 300)
    piece = next(p for p in r.match.pieces if p.owner_id == "a")
    piece.position = Vec(920, 300)
    formation = game._formation_positions(r)
    result = game.move(r, "a", piece.id, {"x": 1, "y": 0}, 1.0, 1)
    assert result["goal"] == "a"
    for match_piece in r.match.pieces:
        assert match_piece.position.x == formation[match_piece.id].x
        assert match_piece.position.y == formation[match_piece.id].y
    assert r.match.ball.position.x == 500
    assert r.match.ball.position.y == 300
