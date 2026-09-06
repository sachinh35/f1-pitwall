import { useCallback, useEffect, useRef } from "react";
import { PositionSample } from "../types/raceMode";
import { interpolatePositionAtTime } from "../utils/positionInterpolation";

// F1's own feed never sends circuit geometry - cars repeatedly tracing the same circuit
// *is* the track shape (see TrackMap.tsx), so each driver's trail is capped rather than
// grown forever across a long session.
const MAX_TRAIL_POINTS_PER_DRIVER = 2000;

export interface PositionPlayback {
  /** A ref, not React state - Position.z arrives several times a second per car, and
   * routing that through component re-renders would jank. TrackMap reads this directly
   * off the ref every animation frame instead. */
  positionsRef: React.MutableRefObject<Record<string, PositionSample>>;
  /** Per-driver history of {x,y} points accumulated over the session - drawn as the track
   * outline in TrackMap. */
  trailRef: React.MutableRefObject<Record<string, { x: number; y: number }[]>>;
  /** Feeds one Position.z message's worth of new samples in - see
   * live_session_pipeline.py's diff_to_wire for why this is a batch per driver, not a
   * single point. */
  feedBatch: (positions: Record<string, PositionSample[]>) => void;
  /** Clears all playback/position/trail state - call when reconnecting to a different
   * stream so the new session doesn't start by rendering the previous one's last frame. */
  reset: () => void;
}

/**
 * Smooths Position.z playback to F1's real ~4Hz sample rate instead of snapping once per
 * incoming SSE message (~1/sec) - see utils/positionInterpolation.ts for the actual
 * interpolation math this wraps in a requestAnimationFrame loop.
 */
export function usePositionPlayback(): PositionPlayback {
  const positionsRef = useRef<Record<string, PositionSample>>({});
  const trailRef = useRef<Record<string, { x: number; y: number }[]>>({});
  const playbackRef = useRef<Record<string, PositionSample[]>>({});

  useEffect(() => {
    let rafId: number;
    const step = () => {
      const now = Date.now();
      const next: Record<string, PositionSample> = { ...positionsRef.current };
      for (const [driverStr, samples] of Object.entries(playbackRef.current)) {
        /* v8 ignore next -- feedBatch never stores an empty sample list (see its own guard); defensive only */
        if (samples.length === 0) continue;
        next[driverStr] = interpolatePositionAtTime(samples, now);
      }
      positionsRef.current = next;
      rafId = requestAnimationFrame(step);
    };
    rafId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const feedBatch = useCallback((positions: Record<string, PositionSample[]>) => {
    for (const [driverStr, samples] of Object.entries(positions)) {
      if (samples.length === 0) continue;
      // Playback is driven entirely off each sample's own absolute utc timestamp (see
      // interpolatePositionAtTime), so the batch just needs to be stored as-is - no
      // arrival-time anchor to compute or maintain.
      playbackRef.current[driverStr] = samples;

      const trail = trailRef.current[driverStr] ?? (trailRef.current[driverStr] = []);
      for (const sample of samples) {
        trail.push({ x: sample.x, y: sample.y });
        if (trail.length > MAX_TRAIL_POINTS_PER_DRIVER) trail.shift();
      }
    }
  }, []);

  const reset = useCallback(() => {
    positionsRef.current = {};
    trailRef.current = {};
    playbackRef.current = {};
  }, []);

  return { positionsRef, trailRef, feedBatch, reset };
}
