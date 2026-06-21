import {useEffect, useRef, useState} from 'react';
import {Flag, Volume2, VolumeX} from 'lucide-react';
import {buildReplayFrames, STEPS_PER_FRAME, type MoveCommand, type ReplayFrame} from './physics';
import {playGoalSound} from './sounds';
import type {Piece, Room} from './types';

const FIELD_WIDTH = 1000;
const FIELD_HEIGHT = 600;
const MAX_PULL = 180;

type Point = {x: number; y: number};
type Aim = {pieceId: string; origin: Point; pull: Point; force: number};

export function GameField({room, userId, send}: {room: Room; userId: string; send: (message: object) => void}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{pieceId: string; origin: Point} | null>(null);
  const visualPositions = useRef(new Map<string, Point>());
  const replayFrames = useRef<ReplayFrame[]>([]);
  const replayIndex = useRef(0);
  const replaySequence = useRef(0);
  const replayTimer = useRef<number | undefined>(undefined);
  const match = room.match!;
  const matchRef = useRef(match);
  matchRef.current = match;
  const photoImages = useRef(new Map<string, HTMLImageElement>());
  const music = useRef<HTMLAudioElement | null>(null);
  const lastCelebratedSeq = useRef(match.sequence);
  const prevScoreRef = useRef<Record<string, number>>({...match.score});
  const expiredDeadlineRef = useRef(0);
  const [aim, setAim] = useState<Aim | null>(null);
  const [renderFrame, setRenderFrame] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [displayScore, setDisplayScore] = useState<Record<string, number>>(() => ({...match.score}));
  const [goalFlash, setGoalFlash] = useState<string | null>(null);
  const ids = Object.keys(room.participants);
  const scoreKey = ids.map(id => `${id}:${match.score[id] ?? 0}`).join('|');
  const myTurn = match.turn_player_id === userId;
  const turnPlayer = room.participants[match.turn_player_id];

  useEffect(() => {
    const audio = new Audio('/match-music.m4a');
    audio.loop = true;
    audio.volume = .35;
    music.current = audio;
    void audio.play().catch(() => {
      // Autoplay may be blocked until the player interacts with the page.
      setSoundEnabled(false);
    });
    return () => {
      audio.pause();
      audio.currentTime = 0;
      music.current = null;
    };
  }, []);

  const toggleSound = () => {
    const audio = music.current;
    if (!audio) return;
    if (soundEnabled) {
      audio.pause();
      setSoundEnabled(false);
      return;
    }
    audio.play().then(() => setSoundEnabled(true)).catch(() => setSoundEnabled(false));
  };

  const celebrateGoal = (scorerId: string, sequence: number, playSound: boolean) => {
    if (sequence <= lastCelebratedSeq.current) return;
    lastCelebratedSeq.current = sequence;
    setDisplayScore(() => {
      const serverScore = matchRef.current.score;
      if (matchRef.current.sequence >= sequence) return {...serverScore};
      return {...serverScore, [scorerId]: (serverScore[scorerId] ?? 0) + 1};
    });
    setGoalFlash(scorerId);
    window.setTimeout(() => setGoalFlash(current => (current === scorerId ? null : current)), 2200);
    if (playSound && soundEnabled) playGoalSound();
  };

  useEffect(() => {
    setDisplayScore({...match.score});
    const prev = prevScoreRef.current;
    for (const id of ids) {
      if ((match.score[id] ?? 0) > (prev[id] ?? 0)) {
        if (match.sequence > lastCelebratedSeq.current) {
          lastCelebratedSeq.current = match.sequence;
          setGoalFlash(id);
          window.setTimeout(() => setGoalFlash(current => (current === id ? null : current)), 2200);
          if (soundEnabled) playGoalSound();
        }
        break;
      }
    }
    prevScoreRef.current = {...match.score};
  }, [scoreKey, match.sequence, soundEnabled]);

  useEffect(() => {
    for (const participant of Object.values(room.participants)) {
      participant.player_photos?.forEach(photo => {
        if (!photo || photoImages.current.has(photo)) return;
        const image = new Image();
        image.onload = () => setRenderFrame(frame => frame + 1);
        image.src = photo;
        photoImages.current.set(photo, image);
      });
    }
  }, [room.participants]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const remaining = Math.max(0, Math.ceil((match.turn_deadline * 1000 - now) / 1000));
    if (remaining > 0 || match.turn_deadline === expiredDeadlineRef.current) return;
    expiredDeadlineRef.current = match.turn_deadline;
    send({type: 'expire_turn'});
  }, [now, match.turn_deadline, send]);

  const syncVisualFromServer = () => {
    for (const piece of match.pieces) visualPositions.current.set(piece.id, {...piece.position});
    visualPositions.current.set(match.ball.id, {...match.ball.position});
    setRenderFrame(frame => frame + 1);
  };

  const piecePosition = (piece: Piece): Point => visualPositions.current.get(piece.id) ?? piece.position;

  const startReplay = (frames: ReplayFrame[], sequence: number, goal: string | null, goalFrame: number | null) => {
    if (!frames.length) return;
    cancelAnimationFrame(replayTimer.current ?? 0);
    replayFrames.current = frames;
    replayIndex.current = 0;
    replaySequence.current = sequence;
    visualPositions.current = new Map(frames[0]);
    setRenderFrame(frame => frame + 1);
    let goalHandled = false;

    const tick = () => {
      const frameIndex = replayIndex.current;
      if (!goalHandled && goal && goalFrame !== null && frameIndex >= goalFrame) {
        goalHandled = true;
        celebrateGoal(goal, sequence, true);
      }
      if (replayIndex.current >= replayFrames.current.length - 1) {
        if (replaySequence.current === matchRef.current.sequence) {
          for (const piece of matchRef.current.pieces) {
            visualPositions.current.set(piece.id, {...piece.position});
          }
          visualPositions.current.set(matchRef.current.ball.id, {...matchRef.current.ball.position});
        } else {
          visualPositions.current = new Map(replayFrames.current[replayFrames.current.length - 1]);
        }
        setRenderFrame(frame => frame + 1);
        return;
      }
      replayIndex.current = Math.min(replayIndex.current + STEPS_PER_FRAME, replayFrames.current.length - 1);
      visualPositions.current = new Map(replayFrames.current[replayIndex.current]);
      setRenderFrame(frame => frame + 1);
      replayTimer.current = requestAnimationFrame(tick);
    };

    replayTimer.current = requestAnimationFrame(tick);
  };

  const startOptimisticReplay = (move: MoveCommand) => {
    const initial: Record<string, Point> = {};
    for (const piece of match.pieces) initial[piece.id] = {...piecePosition(piece)};
    initial.ball = {...piecePosition(match.ball)};
    const replay = buildReplayFrames(match.pieces, match.ball, move, ids, initial);
    startReplay(replay.frames, match.sequence + 1, replay.goal, replay.goalFrame);
  };

  useEffect(() => {
    replaySequence.current = matchRef.current.sequence;
    lastCelebratedSeq.current = matchRef.current.sequence;
    prevScoreRef.current = {...matchRef.current.score};
    syncVisualFromServer();
    return () => cancelAnimationFrame(replayTimer.current ?? 0);
  }, []);

  useEffect(() => {
    if (!match.last_move) {
      syncVisualFromServer();
      return;
    }
    if (replaySequence.current === match.sequence) {
      if (replayIndex.current >= replayFrames.current.length - 1) syncVisualFromServer();
      return;
    }
    const replay = buildReplayFrames(match.pieces, match.ball, match.last_move, ids, match.last_move.initial);
    startReplay(replay.frames, match.sequence, replay.goal, replay.goalFrame);
  }, [match.sequence]);

  useEffect(() => {
    if (!myTurn) {
      drag.current = null;
      setAim(null);
    }
  }, [myTurn]);

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const context = element.getContext('2d')!;
    const dpr = devicePixelRatio || 1;
    const width = element.clientWidth;
    const height = element.clientHeight;
    element.width = width * dpr;
    element.height = height * dpr;
    context.scale(dpr, dpr);
    const scaleX = width / FIELD_WIDTH;
    const scaleY = height / FIELD_HEIGHT;
    const scale = Math.min(scaleX, scaleY);

    context.clearRect(0, 0, width, height);
    context.strokeStyle = 'rgba(255,255,255,.8)';
    context.lineWidth = 3;
    context.strokeRect(18 * scaleX, 18 * scaleY, 964 * scaleX, 564 * scaleY);
    context.beginPath();
    context.moveTo(500 * scaleX, 18 * scaleY);
    context.lineTo(500 * scaleX, 582 * scaleY);
    context.stroke();
    context.beginPath();
    context.arc(500 * scaleX, 300 * scaleY, 82 * scale, 0, Math.PI * 2);
    context.stroke();
    for (const x of [18, 842]) context.strokeRect(x * scaleX, 190 * scaleY, 140 * scaleX, 220 * scaleY);

    const drawPiece = (piece: Piece) => {
      const position = visualPositions.current.get(piece.id) ?? piece.position;
      const x = position.x * scaleX;
      const y = position.y * scaleY;
      const radius = piece.radius * scale;
      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      if (piece.role === 'ball') {
        context.fillStyle = '#fff';
        context.fill();
        context.font = `${radius * 1.5}px sans-serif`;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText('⚽', x, y);
        return;
      }
      const owner = room.participants[piece.owner_id];
      const selectable = myTurn && piece.owner_id === userId;
      context.globalAlpha = myTurn && !selectable ? .72 : 1;
      context.fillStyle = owner.primary;
      context.fill();
      const pieceIndex = piece.role === 'goalkeeper' ? 3 : Number(piece.id.match(/-p(\d+)$/)?.[1] ?? -1);
      const photo = owner.player_photos?.[pieceIndex];
      const photoImage = photo ? photoImages.current.get(photo) : undefined;
      if (photoImage?.complete && photoImage.naturalWidth) {
        context.save();
        context.beginPath();
        context.arc(x, y, radius - 2, 0, Math.PI * 2);
        context.clip();
        context.drawImage(photoImage, x - radius, y - radius, radius * 2, radius * 2);
        context.restore();
      }
      context.lineWidth = drag.current?.pieceId === piece.id ? 7 : 5;
      context.strokeStyle = drag.current?.pieceId === piece.id ? '#fde047' : owner.secondary;
      context.stroke();
      if (!photoImage?.complete || !photoImage.naturalWidth) {
        context.fillStyle = '#fff';
        context.font = `bold ${radius * .8}px sans-serif`;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(owner.name[0].toUpperCase(), x, y);
      }
      context.globalAlpha = 1;
    };

    match.pieces.forEach(drawPiece);
    drawPiece(match.ball);

    if (aim) {
      const originX = aim.origin.x * scaleX;
      const originY = aim.origin.y * scaleY;
      const pullX = aim.pull.x * scaleX;
      const pullY = aim.pull.y * scaleY;
      const shotX = originX + (originX - pullX) * 1.15;
      const shotY = originY + (originY - pullY) * 1.15;
      context.setLineDash([8, 8]);
      context.strokeStyle = 'rgba(255,255,255,.75)';
      context.lineWidth = 3;
      context.beginPath();
      context.moveTo(originX, originY);
      context.lineTo(pullX, pullY);
      context.stroke();
      context.setLineDash([]);
      context.strokeStyle = aim.force > .72 ? '#fb7185' : '#fde047';
      context.lineWidth = 5;
      context.beginPath();
      context.moveTo(originX, originY);
      context.lineTo(shotX, shotY);
      context.stroke();
      const angle = Math.atan2(shotY - originY, shotX - originX);
      context.fillStyle = context.strokeStyle;
      context.beginPath();
      context.moveTo(shotX, shotY);
      context.lineTo(shotX - 15 * Math.cos(angle - .45), shotY - 15 * Math.sin(angle - .45));
      context.lineTo(shotX - 15 * Math.cos(angle + .45), shotY - 15 * Math.sin(angle + .45));
      context.closePath();
      context.fill();
    }
  }, [room, aim, myTurn, renderFrame, userId]);

  const fieldPoint = (event: React.PointerEvent): Point => {
    const rect = canvas.current!.getBoundingClientRect();
    return {x: (event.clientX - rect.left) * FIELD_WIDTH / rect.width, y: (event.clientY - rect.top) * FIELD_HEIGHT / rect.height};
  };

  const aimFromPoint = (pieceId: string, origin: Point, point: Point): Aim => {
    const dx = point.x - origin.x;
    const dy = point.y - origin.y;
    const distance = Math.hypot(dx, dy);
    const ratio = distance > MAX_PULL ? MAX_PULL / distance : 1;
    const pull = {x: origin.x + dx * ratio, y: origin.y + dy * ratio};
    return {pieceId, origin, pull, force: Math.min(1, distance / MAX_PULL)};
  };

  const updateAim = (point: Point) => {
    if (!drag.current) return;
    setAim(aimFromPoint(drag.current.pieceId, drag.current.origin, point));
  };

  const handlePointerDown = (event: React.PointerEvent) => {
    if (!myTurn) return;
    const point = fieldPoint(event);
    const piece = match.pieces.find(candidate => candidate.owner_id === userId && Math.hypot(piecePosition(candidate).x - point.x, piecePosition(candidate).y - point.y) < candidate.radius * 1.55);
    if (!piece) return;
    event.preventDefault();
    const origin = {...piecePosition(piece)};
    drag.current = {pieceId: piece.id, origin};
    setAim(aimFromPoint(piece.id, origin, origin));
    canvas.current!.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent) => {
    if (drag.current) updateAim(fieldPoint(event));
  };

  const finishDrag = (event: React.PointerEvent, shoot: boolean) => {
    if (!drag.current) return;
    const {pieceId, origin} = drag.current;
    if (canvas.current?.hasPointerCapture(event.pointerId)) canvas.current.releasePointerCapture(event.pointerId);
    if (shoot && myTurn) {
      const shot = aimFromPoint(pieceId, origin, fieldPoint(event));
      if (shot.force >= .06) {
        const move = {
          type: 'move' as const,
          piece_id: pieceId,
          direction: {x: origin.x - shot.pull.x, y: origin.y - shot.pull.y},
          force: shot.force,
          sequence: match.sequence + 1,
        };
        startOptimisticReplay(move);
        send(move);
      }
    }
    drag.current = null;
    setAim(null);
  };

  const seconds = Math.max(0, Math.ceil((match.turn_deadline * 1000 - now) / 1000));
  const power = Math.round((aim?.force ?? 0) * 100);

  return <main className="game">
    <div className={`scorebar ${goalFlash ? 'goal-flash' : ''}`}><div><i style={{background: room.participants[ids[0]].primary}}>{room.participants[ids[0]].name[0]}</i><b>{room.participants[ids[0]].team_name}</b></div><strong>{displayScore[ids[0]] ?? 0} <span>×</span> {displayScore[ids[1]] ?? 0}</strong><div><b>{room.participants[ids[1]].team_name}</b><i style={{background: room.participants[ids[1]].primary}}>{room.participants[ids[1]].name[0]}</i></div></div>
    {goalFlash && <div className="goal-banner" aria-live="assertive">GOOOOL!</div>}
    <div className={`turn ${myTurn ? 'is-mine' : ''}`} style={{'--turn-color': turnPlayer.primary} as React.CSSProperties} aria-live="polite"><span><i style={{background: turnPlayer.primary}} />{myTurn ? `SUA VEZ, ${turnPlayer.name.toUpperCase()}!` : `VEZ DE ${turnPlayer.name.toUpperCase()}`}</span><b>{seconds}s</b><small>{turnPlayer.team_name} • {match.turns_left} jogadas restantes</small></div>
    <div className={`field-wrap ${myTurn ? 'can-play' : 'waiting-turn'} ${aim ? 'aiming' : ''}`}><canvas ref={canvas} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={event => finishDrag(event, true)} onPointerCancel={event => finishDrag(event, false)} /></div>
    <div className="shot-control"><div className="game-hint">{myTurn ? (aim ? 'Solte para chutar na direção da seta' : 'Puxe uma peça para trás e solte para chutar') : `Aguarde: ${turnPlayer.name} está jogando`}</div><div className={`power-meter ${aim ? 'visible' : ''}`} aria-label={`Força do chute: ${power}%`}><span>FORÇA</span><div><i style={{width: `${power}%`}} /></div><b>{power}%</b></div></div>
    <div className="game-tools"><button onClick={() => send({type: 'forfeit'})}><Flag />Desistir</button><button onClick={toggleSound} aria-pressed={soundEnabled}>{soundEnabled ? <Volume2 /> : <VolumeX />}{soundEnabled ? 'Som' : 'Som desligado'}</button></div>
  </main>;
}
