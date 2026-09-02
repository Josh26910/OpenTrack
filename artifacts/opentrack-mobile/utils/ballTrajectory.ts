/**
 * Physics-assisted projectile fit for the Ball Tracker feature.
 *
 * Ported from the OpenTrack Studio desktop editor's `_fit_trajectory` /
 * `_compute_stats` (and its Swift port) — see that project's
 * launch_monitor_editor_10_5.py for the original derivation notes.
 *
 * Both x(t) and y(t) are modelled as quadratics in time — the shape of
 * constant-acceleration projectile motion. A weighted least-squares fit
 * gives the overall stats (launch angle), while the on-screen path is
 * built segment-by-segment so it always passes exactly through every
 * clicked frame and only "invents" motion across the gaps the user
 * didn't click (last-launch -> apex, apex -> landing).
 */

export type Point = { x: number; y: number };
export type FrameClick = { frame: number; point: Point };
export type QuadCoeffs = { a: number; b: number; c: number };

export const evalQuad = (q: QuadCoeffs, t: number) => q.a * t * t + q.b * t + q.c;

export type StatKey = "ballSpeed" | "carry" | "launch" | "height";

export const STAT_DEFS: Record<StatKey, { label: string; unit: string; decimals: number; bounds: [number, number] }> = {
  ballSpeed: { label: "BALL SPEED", unit: "mph", decimals: 1, bounds: [1, 230] },
  carry: { label: "CARRY", unit: "yds", decimals: 1, bounds: [1, 420] },
  launch: { label: "LAUNCH ANGLE", unit: "deg", decimals: 1, bounds: [-15, 60] },
  height: { label: "HEIGHT (APEX)", unit: "ft", decimals: 0, bounds: [1, 220] },
};

export const YPS_TO_MPH = 3600 / 1760;
export const YARDS_TO_FEET = 3.0;

export type DistanceUnit = "yards" | "feet" | "meters" | "inches";
export const UNIT_TO_YARDS: Record<DistanceUnit, number> = {
  yards: 1.0,
  feet: 1.0 / 3.0,
  meters: 1.09361,
  inches: 1.0 / 36.0,
};

// ---------------------------------------------------------------------
// Weighted quadratic fit (closed-form 3x3 normal-equations solve — the
// model is linear in its coefficients, so no iterative solver needed).
// ---------------------------------------------------------------------

function solve3x3(m: number[][]): number[] {
  const a = m.map((row) => row.slice());
  for (let col = 0; col < 3; col++) {
    let pivot = col;
    for (let row = col + 1; row < 3; row++) {
      if (Math.abs(a[row][col]) > Math.abs(a[pivot][col])) pivot = row;
    }
    [a[col], a[pivot]] = [a[pivot], a[col]];
    const pv = a[col][col];
    if (Math.abs(pv) <= 1e-12) continue;
    for (let row = 0; row < 3; row++) {
      if (row === col) continue;
      const factor = a[row][col] / pv;
      for (let k = col; k <= 3; k++) a[row][k] -= factor * a[col][k];
    }
  }
  return [0, 1, 2].map((i) => (Math.abs(a[i][i]) > 1e-12 ? a[i][3] / a[i][i] : 0));
}

export function weightedQuadFit(t: number[], y: number[], weights: number[]): QuadCoeffs {
  const s = [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
  ];
  for (let i = 0; i < t.length; i++) {
    const w = weights[i], ti = t[i], yi = y[i];
    const t2 = ti * ti, t3 = t2 * ti, t4 = t2 * t2;
    s[0][0] += w * t4; s[0][1] += w * t3; s[0][2] += w * t2; s[0][3] += w * t2 * yi;
    s[1][0] += w * t3; s[1][1] += w * t2; s[1][2] += w * ti; s[1][3] += w * ti * yi;
    s[2][0] += w * t2; s[2][1] += w * ti; s[2][2] += w;      s[2][3] += w * yi;
  }
  const [a, b, c] = solve3x3(s);
  return { a, b, c };
}

function linregSlope(pts: [number, number][]): number {
  const n = pts.length;
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const [x, y] of pts) { sx += x; sy += y; sxx += x * x; sxy += x * y; }
  const denom = n * sxx - sx * sx;
  if (Math.abs(denom) < 1e-9) return 0;
  return (n * sxy - sx * sy) / denom;
}

// ---------------------------------------------------------------------
// Segmented display path
// ---------------------------------------------------------------------

const GAP_THRESHOLD = 5;
const V0_TRAIL_POINTS = 4;
const V0_TRAIL_SPAN = 12;

function monotoneV0(v: number, d: number, t: number): number {
  const lo = Math.min(0, (2 * d) / t), hi = Math.max(0, (2 * d) / t);
  return Math.min(Math.max(v, lo), hi);
}

/** Returns [holdFrames, easePower|null, tooSlow]. See Swift port for full derivation. */
function holdThenEase(v0: number, d: number, t: number): [number, number | null, boolean] {
  const r = Math.abs(d) > 1e-6 ? (v0 * t) / d : 2.0;
  if (r <= 1.0) return [0, null, true];
  if (r <= 2.0) return [(t * (2.0 - r)) / r, null, false];
  return [0, r - 1.0, false];
}

function buildSegmentedTrajectory(pts: FrameClick[], nLaunch: number): Map<number, Point> {
  const traj = new Map<number, Point>();
  let prevEndVel: [number, number] | null = null;
  let prevWasCurve = false;

  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    traj.set(a.frame, a.point);
    const gap = b.frame - a.frame;

    if (gap < GAP_THRESHOLD) {
      if (gap >= 1) {
        for (let f = a.frame + 1; f < b.frame; f++) {
          const frac = (f - a.frame) / gap;
          traj.set(f, {
            x: a.point.x + (b.point.x - a.point.x) * frac,
            y: a.point.y + (b.point.y - a.point.y) * frac,
          });
        }
        prevEndVel = [(b.point.x - a.point.x) / gap, (b.point.y - a.point.y) / gap];
        prevWasCurve = false;
      }
      continue;
    }

    const T = gap;
    const Dx = b.point.x - a.point.x, Dy = b.point.y - a.point.y;

    let vIn: [number, number];
    if (prevWasCurve && prevEndVel) {
      vIn = prevEndVel;
    } else {
      const trail = pts
        .slice(0, i + 1)
        .filter((p) => a.frame - p.frame <= V0_TRAIL_SPAN)
        .slice(-V0_TRAIL_POINTS);
      if (trail.length >= 2) {
        const txs: [number, number][] = trail.map((p) => [p.frame, p.point.x]);
        const tys: [number, number][] = trail.map((p) => [p.frame, p.point.y]);
        vIn = [linregSlope(txs), linregSlope(tys)];
      } else if (prevEndVel) {
        vIn = prevEndVel;
      } else {
        vIn = [Dx / T, Dy / T];
      }
    }

    const v0x = monotoneV0(vIn[0], Dx, T);
    const sax = (2.0 * (Dx - v0x * T)) / (T * T);

    const endsAtApex = i + 1 === nLaunch;
    const startsAtApex = i === nLaunch;

    let holdH: number | null = null;
    let easeP: number | null = null;
    let m0y = 0, v0y = 0, say = 0, vyEnd = 0;

    if (startsAtApex) {
      vyEnd = (2.0 * Dy) / T;
    } else if (endsAtApex) {
      const [h, ep, tooSlow] = holdThenEase(vIn[1], Dy, T);
      if (tooSlow) {
        const lo = Math.min(0, (3.0 * Dy) / T), hi = Math.max(0, (3.0 * Dy) / T);
        m0y = Math.min(Math.max(vIn[1], lo), hi);
      } else if (ep === null) {
        holdH = h;
      } else {
        easeP = ep;
      }
      vyEnd = 0;
    } else {
      v0y = monotoneV0(vIn[1], Dy, T);
      say = (2.0 * (Dy - v0y * T)) / (T * T);
      vyEnd = v0y + say * T;
    }

    if (gap > 1) {
      for (let f = a.frame + 1; f < b.frame; f++) {
        const tau = f - a.frame;
        const x = a.point.x + v0x * tau + 0.5 * sax * tau * tau;
        let y: number;
        if (endsAtApex && easeP !== null) {
          const frac = 1.0 - Math.pow(1.0 - tau / T, easeP + 1.0);
          y = a.point.y + Dy * frac;
        } else if (endsAtApex && holdH !== null) {
          if (tau <= holdH) {
            y = a.point.y + vIn[1] * tau;
          } else {
            const eTau = tau - holdH, E = T - holdH;
            const sy = a.point.y + vIn[1] * holdH;
            y = sy + vIn[1] * eTau - 0.5 * (vIn[1] / E) * eTau * eTau;
          }
        } else if (endsAtApex) {
          const s = tau / T;
          const h00 = (2.0 * s - 3.0) * s * s + 1.0;
          const h10 = ((s - 2.0) * s + 1.0) * s;
          y = h00 * a.point.y + (1.0 - h00) * b.point.y + h10 * T * m0y;
        } else if (startsAtApex) {
          y = a.point.y + Dy * Math.pow(tau / T, 2);
        } else {
          y = a.point.y + v0y * tau + 0.5 * say * tau * tau;
        }
        traj.set(f, { x, y });
      }
    }
    prevEndVel = [v0x + sax * T, vyEnd];
    prevWasCurve = true;
  }
  const last = pts[pts.length - 1];
  if (last) traj.set(last.frame, last.point);
  return traj;
}

export type FitResult = {
  trajectory: Map<number, Point>;
  fitX: QuadCoeffs;
  fitY: QuadCoeffs;
  impactFrame: number;
  apexFrame: number;
  landingFrame: number;
};

export function fitTrajectory(launchClicks: FrameClick[], apex: FrameClick, landing: FrameClick, fps: number): FitResult {
  const f0 = launchClicks[0].frame;
  const pts = [...launchClicks, apex, landing];

  const ts = pts.map((p) => (p.frame - f0) / fps);
  const xs = pts.map((p) => p.point.x);
  const ys = pts.map((p) => p.point.y);

  const weights = pts.map(() => 1.0);
  weights[0] = 5.0;
  const nLaunch = launchClicks.length;
  weights[nLaunch] = 8.0;
  weights[nLaunch + 1] = 8.0;

  const fitX = weightedQuadFit(ts, xs, weights);
  const fitY = weightedQuadFit(ts, ys, weights);
  const trajectory = buildSegmentedTrajectory(pts, nLaunch);

  return { trajectory, fitX, fitY, impactFrame: f0, apexFrame: apex.frame, landingFrame: landing.frame };
}

// ---------------------------------------------------------------------
// Live (pre-track) preview: cheap piecewise-linear path so the ring
// follows the ball immediately as the user clicks, before "Track Shot".
// ---------------------------------------------------------------------

export function livePreviewTrajectory(
  launchClicks: FrameClick[],
  apex: FrameClick | null,
  landing: FrameClick | null,
): Map<number, Point> {
  const points = [...launchClicks];
  if (apex) points.push(apex);
  if (landing) points.push(landing);
  const seen = new Set<number>();
  const uniq = points
    .slice()
    .sort((a, b) => a.frame - b.frame)
    .filter((p) => (seen.has(p.frame) ? false : (seen.add(p.frame), true)));
  const traj = new Map<number, Point>();
  if (uniq.length < 2) return traj;
  for (let i = 0; i < uniq.length - 1; i++) {
    const a = uniq[i], b = uniq[i + 1];
    const gap = b.frame - a.frame;
    if (gap <= 0) continue;
    for (let f = a.frame; f <= b.frame; f++) {
      const t = (f - a.frame) / gap;
      traj.set(f, { x: a.point.x + (b.point.x - a.point.x) * t, y: a.point.y + (b.point.y - a.point.y) * t });
    }
  }
  return traj;
}

// ---------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------

export type Stats = Partial<Record<StatKey, number>>;

export function computeStats(
  launchClicks: FrameClick[],
  apex: FrameClick,
  landing: FrameClick,
  fitX: QuadCoeffs,
  fitY: QuadCoeffs,
  fps: number,
  yardsPerPixel: number | null,
): { stats: Stats; warnings: Set<StatKey> } {
  const stats: Stats = {};

  const pxSpeeds: number[] = [];
  for (let i = 0; i < launchClicks.length - 1; i++) {
    const a = launchClicks[i], b = launchClicks[i + 1];
    const df = b.frame - a.frame;
    if (df <= 0) continue;
    const dist = Math.hypot(b.point.x - a.point.x, b.point.y - a.point.y);
    pxSpeeds.push((dist * fps) / df);
  }
  const pxPerS = pxSpeeds.length ? pxSpeeds.reduce((s, v) => s + v, 0) / pxSpeeds.length : 0;
  if (yardsPerPixel !== null && pxPerS > 0) {
    stats.ballSpeed = pxPerS * yardsPerPixel * YPS_TO_MPH;
  }

  const vx0 = fitX.b, vy0 = -fitY.b;
  if (Math.abs(vx0) > 1e-6 || Math.abs(vy0) > 1e-6) {
    stats.launch = (Math.atan2(vy0, Math.abs(vx0)) * 180) / Math.PI;
  }

  const first = launchClicks[0];
  if (yardsPerPixel !== null) {
    stats.carry = Math.hypot(landing.point.x - first.point.x, landing.point.y - first.point.y) * yardsPerPixel;
  }

  if (yardsPerPixel !== null) {
    let yApex: number;
    if (Math.abs(fitY.a) > 1e-9) {
      const tApex = -fitY.b / (2.0 * fitY.a);
      yApex = evalQuad(fitY, tApex);
    } else {
      yApex = apex.point.y;
    }
    const hPx = Math.max(0, first.point.y - yApex);
    stats.height = hPx * yardsPerPixel * YARDS_TO_FEET;
  }

  const warnings = new Set<StatKey>();
  (Object.keys(stats) as StatKey[]).forEach((key) => {
    const val = stats[key];
    if (val === undefined) return;
    const [lo, hi] = STAT_DEFS[key].bounds;
    if (val < lo || val > hi) warnings.add(key);
  });

  return { stats, warnings };
}
