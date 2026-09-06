/**
 * Pure math for smoothing Position.z playback (see hooks/usePositionPlayback.ts).
 *
 * The backend forwards F1's whole ~4Hz Position.z batch per driver (~5 real samples
 * spaced ~260ms apart) instead of just the newest point - see
 * live/live_session_pipeline.py's diff_to_wire. Kept separate from the hook so the
 * interpolation math itself (given a batch and the current absolute time, what point
 * should be on screen right now) is testable without faking requestAnimationFrame.
 */
import { PositionSample } from "../types/raceMode";

function parseUtc(sample: PositionSample): number {
  return sample.utc ? Date.parse(sample.utc) : NaN;
}

function stripUtc(sample: PositionSample): PositionSample {
  return { x: sample.x, y: sample.y, z: sample.z, status: sample.status };
}

/**
 * The point that should be on screen at absolute time `nowMs` (client wall-clock ms
 * since epoch - directly comparable to each sample's own `utc`, F1's real capture
 * timestamp for that point), linearly interpolated between the two real samples
 * straddling that instant.
 *
 * Driving playback off each sample's own absolute timestamp - rather than a duration
 * anchored to whenever this batch happened to arrive over SSE - is what keeps motion
 * continuous across batch boundaries. F1's Position.z messages arrive with real jitter
 * (confirmed live: 0.85s-1.15s between messages, not a steady 1.0s); anchoring to
 * arrival time meant every batch boundary either cut the previous batch's animation off
 * mid-flight (an early arrival) or froze on the last known point and then snapped
 * straight to the new batch's first sample (a late arrival) - both visible as jerky,
 * stepped motion despite each batch's real intermediate samples being available to
 * interpolate through. Falls back to the batch's last sample if fewer than two samples
 * are given, or if any timestamp involved is missing/unparseable (e.g. an older wire
 * payload that predates the `utc` field).
 */
export function interpolatePositionAtTime(samples: PositionSample[], nowMs: number): PositionSample {
  const last = samples[samples.length - 1];
  if (samples.length < 2) return stripUtc(last);

  const firstT = parseUtc(samples[0]);
  const lastT = parseUtc(last);
  if (Number.isNaN(firstT) || Number.isNaN(lastT)) return stripUtc(last);

  if (nowMs <= firstT) return stripUtc(samples[0]);
  if (nowMs >= lastT) return stripUtc(last);

  for (let i = 0; i < samples.length - 1; i++) {
    const t0 = parseUtc(samples[i]);
    const t1 = parseUtc(samples[i + 1]);
    /* v8 ignore next -- every real sample carries utc (see live_session_pipeline.py's
       diff_to_wire); firstT/lastT above already guard the only realistic missing case. */
    if (Number.isNaN(t0) || Number.isNaN(t1)) continue;
    if (nowMs >= t0 && nowMs <= t1) {
      // t1 > t0 is guaranteed here: a tie (t0 === t1 === nowMs) would already have
      // matched the *previous* segment's t1 (same instant) first, or - for the very
      // first segment - been caught by the nowMs <= firstT guard above.
      const localT = (nowMs - t0) / (t1 - t0);
      const a = samples[i];
      const b = samples[i + 1];
      return {
        x: a.x + (b.x - a.x) * localT,
        y: a.y + (b.y - a.y) * localT,
        z: a.z + (b.z - a.z) * localT,
        status: b.status,
      };
    }
  }
  /* v8 ignore next -- firstT <= nowMs <= lastT is guaranteed above, so some consecutive
     pair always straddles nowMs; unreachable, defensive only. */
  return stripUtc(last);
}
