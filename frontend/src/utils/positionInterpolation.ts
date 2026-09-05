/**
 * Pure math for smoothing Position.z playback (see hooks/usePositionPlayback.ts).
 *
 * The backend forwards F1's whole ~4Hz Position.z batch per driver (~5 real samples
 * spaced ~260ms apart) instead of just the newest point - see
 * live/live_session_pipeline.py's diff_to_wire. Kept separate from the hook so the
 * interpolation math itself (given a batch and an elapsed time, what point should be on
 * screen right now) is testable without faking requestAnimationFrame/performance.now().
 */
import { PositionSample } from "../types/raceMode";

/**
 * The batch's own real time span, in milliseconds, from its first sample's `utc` to its
 * last - the duration playback should take to traverse the whole batch. Falls back to 0
 * (snap immediately to the last sample) if either endpoint's timestamp is missing or
 * unparseable, e.g. an older wire payload that predates the `utc` field.
 */
export function computeBatchDurationMs(samples: PositionSample[]): number {
  if (samples.length === 0) return 0;
  const firstUtc = samples[0].utc ? Date.parse(samples[0].utc) : NaN;
  const lastUtc = samples[samples.length - 1].utc ? Date.parse(samples[samples.length - 1].utc!) : NaN;
  if (Number.isNaN(firstUtc) || Number.isNaN(lastUtc)) return 0;
  return Math.max(0, lastUtc - firstUtc);
}

/**
 * The point that should be on screen `elapsedMs` into playing back `samples` over
 * `durationMs` - linearly interpolated between the two real samples straddling that
 * moment (not just the two endpoints), so on-screen motion follows F1's actual
 * intermediate telemetry rather than a single start->end guess. `elapsedMs` before 0 or
 * past `durationMs` clamps to the first/last sample; `durationMs` of 0 (or `samples` of
 * length 1) always returns the last sample.
 */
export function interpolatePositionSample(
  samples: PositionSample[],
  elapsedMs: number,
  durationMs: number
): PositionSample {
  const frac = durationMs > 0 ? Math.min(1, Math.max(0, elapsedMs / durationMs)) : 1;
  const scaled = frac * (samples.length - 1);
  const i0 = Math.floor(scaled);
  const i1 = Math.min(i0 + 1, samples.length - 1);
  const localT = scaled - i0;
  const a = samples[i0];
  const b = samples[i1];
  return {
    x: a.x + (b.x - a.x) * localT,
    y: a.y + (b.y - a.y) * localT,
    z: a.z + (b.z - a.z) * localT,
    status: b.status,
  };
}
