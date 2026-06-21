import type {Piece} from './types';

export const FIELD_W = 1000;
export const FIELD_H = 600;
const GOAL_Y1 = 220;
const GOAL_Y2 = 380;
const MAX_STEPS = 360;
const STEPS_PER_FRAME = 2;

export type SimBody = {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  isBall: boolean;
};

export type MoveCommand = {
  piece_id: string;
  direction: {x: number; y: number};
  force: number;
};

export type ReplayFrame = Map<string, {x: number; y: number}>;

function hypot(x: number, y: number) {
  return Math.hypot(x, y);
}

export function bodiesFromMatch(pieces: Piece[], ball: Piece, initial?: Record<string, {x: number; y: number}>): SimBody[] {
  const read = (id: string, piece: Piece) => initial?.[id] ?? piece.position;
  return [
    ...pieces.map(piece => ({
      id: piece.id,
      x: read(piece.id, piece).x,
      y: read(piece.id, piece).y,
      vx: 0,
      vy: 0,
      radius: piece.radius,
      isBall: false,
    })),
    {
      id: ball.id,
      x: read(ball.id, ball).x,
      y: read(ball.id, ball).y,
      vx: 0,
      vy: 0,
      radius: ball.radius,
      isBall: true,
    },
  ];
}

export function applyMove(bodies: SimBody[], move: MoveCommand) {
  const piece = bodies.find(body => body.id === move.piece_id);
  if (!piece) return;
  const length = hypot(move.direction.x, move.direction.y);
  if (length < 0.01) return;
  piece.vx = (move.direction.x / length) * move.force * 25;
  piece.vy = (move.direction.y / length) * move.force * 25;
}

function snapshot(bodies: SimBody[]): ReplayFrame {
  return new Map(bodies.map(body => [body.id, {x: body.x, y: body.y}]));
}

export function formationPositions(playerIds: string[]) {
  const positions = new Map<string, {x: number; y: number}>();
  const ys = [190, 300, 410];
  playerIds.forEach((playerId, side) => {
    const x = side === 0 ? 255 : 745;
    ys.forEach((y, index) => positions.set(`${playerId}-p${index}`, {x, y}));
    positions.set(`${playerId}-gk`, {x: side === 0 ? 78 : 922, y: 300});
  });
  return positions;
}

function resetAfterGoal(bodies: SimBody[], playerIds: string[]) {
  const formation = formationPositions(playerIds);
  for (const body of bodies) {
    body.vx = 0;
    body.vy = 0;
    if (body.isBall) {
      body.x = 500;
      body.y = 300;
      continue;
    }
    const position = formation.get(body.id);
    if (position) {
      body.x = position.x;
      body.y = position.y;
    }
  }
}

function simulationStep(bodies: SimBody[], scorePlayerIds: string[]): {goal: string | null; moving: boolean} {
  let moving = false;

  for (const body of bodies) {
    body.x += body.vx;
    body.y += body.vy;
    body.vx *= 0.965;
    body.vy *= 0.965;
    if (hypot(body.vx, body.vy) > 0.06) moving = true;
    else {
      body.vx = 0;
      body.vy = 0;
    }

    if (body.isBall && GOAL_Y1 < body.y && body.y < GOAL_Y2) {
      if (body.x < -body.radius) return {goal: scorePlayerIds[1] ?? scorePlayerIds[0], moving: false};
      if (body.x > FIELD_W + body.radius) return {goal: scorePlayerIds[0] ?? scorePlayerIds[1], moving: false};
    }

    if (body.y < body.radius || body.y > FIELD_H - body.radius) {
      body.y = Math.max(body.radius, Math.min(FIELD_H - body.radius, body.y));
      body.vy *= -0.72;
    }

    if (body.x < body.radius || body.x > FIELD_W - body.radius) {
      if (body.isBall && GOAL_Y1 < body.y && body.y < GOAL_Y2) {
        // allow ball to enter the goal mouth
      } else {
        body.x = Math.max(body.radius, Math.min(FIELD_W - body.radius, body.x));
        body.vx *= -0.72;
      }
    }
  }

  for (let i = 0; i < bodies.length; i++) {
    for (let j = i + 1; j < bodies.length; j++) {
      const a = bodies[i];
      const b = bodies[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = hypot(dx, dy);
      const minimum = a.radius + b.radius;
      if (dist <= 0 || dist >= minimum) continue;
      const nx = dx / dist;
      const ny = dy / dist;
      const overlap = (minimum - dist) / 2;
      a.x -= nx * overlap;
      a.y -= ny * overlap;
      b.x += nx * overlap;
      b.y += ny * overlap;
      const impulse = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
      if (impulse > 0) {
        a.vx -= impulse * nx;
        a.vy -= impulse * ny;
        b.vx += impulse * nx;
        b.vy += impulse * ny;
      }
    }
  }

  return {goal: null, moving};
}

export type ReplayResult = {
  frames: ReplayFrame[];
  goal: string | null;
  goalFrame: number | null;
};

export function buildReplayFrames(
  pieces: Piece[],
  ball: Piece,
  move: MoveCommand,
  scorePlayerIds: string[],
  initial?: Record<string, {x: number; y: number}>,
): ReplayResult {
  const bodies = bodiesFromMatch(pieces, ball, initial);
  applyMove(bodies, move);
  const frames: ReplayFrame[] = [snapshot(bodies)];
  let goal: string | null = null;
  let goalFrame: number | null = null;

  for (let step = 0; step < MAX_STEPS; step++) {
    const stepResult = simulationStep(bodies, scorePlayerIds);
    frames.push(snapshot(bodies));
    if (stepResult.goal) {
      goal = stepResult.goal;
      goalFrame = frames.length - 1;
      resetAfterGoal(bodies, scorePlayerIds);
      frames.push(snapshot(bodies));
      break;
    }
    if (!stepResult.moving) break;
  }

  return {frames, goal, goalFrame};
}

export {STEPS_PER_FRAME};
