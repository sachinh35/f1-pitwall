import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePositionPlayback } from "./usePositionPlayback";
import { PositionSample } from "../types/raceMode";

function sample(x: number, y: number, utc: string): PositionSample {
  return { x, y, z: 0, status: "OnTrack", utc };
}

describe("usePositionPlayback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with empty positions/trails", () => {
    const { result } = renderHook(() => usePositionPlayback());
    expect(result.current.positionsRef.current).toEqual({});
    expect(result.current.trailRef.current).toEqual({});
  });

  it("plays a fed batch back by each sample's own absolute timestamp", () => {
    const { result } = renderHook(() => usePositionPlayback());
    const samples = [
      sample(0, 0, "2026-01-01T00:00:00.000Z"),
      sample(10, 10, "2026-01-01T00:00:01.000Z"),
    ];

    act(() => {
      result.current.feedBatch({ "44": samples });
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Frame-quantized (~16ms rAF ticks under fake timers), so this lands close to, not
    // exactly on, the midpoint - the interpolation math itself is covered precisely in
    // positionInterpolation.test.ts; this test is about the hook actually wiring it up.
    const midpoint = result.current.positionsRef.current["44"];
    expect(midpoint.x).toBeCloseTo(5, 0);
    expect(midpoint.y).toBeCloseTo(5, 0);
  });

  it("reaches the last sample once real time passes its own timestamp", () => {
    const { result } = renderHook(() => usePositionPlayback());
    const samples = [
      sample(0, 0, "2026-01-01T00:00:00.000Z"),
      sample(10, 10, "2026-01-01T00:00:01.000Z"),
    ];

    act(() => {
      result.current.feedBatch({ "44": samples });
    });
    act(() => {
      vi.advanceTimersByTime(1100); // past the last sample's own timestamp
    });

    expect(result.current.positionsRef.current["44"]).toEqual({ x: 10, y: 10, z: 0, status: "OnTrack" });
  });

  it(
    "keeps playback continuous across a batch replacement instead of restarting from " +
      "the new batch's first sample - regression test for the arrival-time-anchored " +
      "design that caused visible jerky motion under real SSE jitter (messages arriving " +
      "0.85s-1.15s apart instead of a steady 1.0s)",
    () => {
      const { result } = renderHook(() => usePositionPlayback());
      act(() => {
        result.current.feedBatch({
          "44": [sample(0, 0, "2026-01-01T00:00:00.000Z"), sample(10, 10, "2026-01-01T00:00:01.000Z")],
        });
      });

      // A new batch arrives early (900ms in, before the first batch's 1000ms span
      // finished) picking up right where the driver actually was - no discontinuity.
      act(() => {
        vi.advanceTimersByTime(900);
      });
      act(() => {
        result.current.feedBatch({
          "44": [sample(9, 9, "2026-01-01T00:00:00.900Z"), sample(19, 19, "2026-01-01T00:00:01.900Z")],
        });
      });
      act(() => {
        vi.advanceTimersByTime(20); // let a fresh rAF tick pick up the replaced batch
      });

      // Both the old batch (extrapolated past ~900ms) and the new one agree on ~9 here -
      // the point is there's no jump backward/forward from a mismatched re-anchor.
      const position = result.current.positionsRef.current["44"];
      expect(position.x).toBeCloseTo(9, 0);
      expect(position.y).toBeCloseTo(9, 0);
    }
  );

  it("accumulates every sample of a batch into the driver's trail", () => {
    const { result } = renderHook(() => usePositionPlayback());
    const samples = [
      sample(0, 0, "2026-01-01T00:00:00.000Z"),
      sample(10, 10, "2026-01-01T00:00:01.000Z"),
    ];

    act(() => {
      result.current.feedBatch({ "44": samples });
    });

    expect(result.current.trailRef.current["44"]).toEqual([
      { x: 0, y: 0 },
      { x: 10, y: 10 },
    ]);
  });

  it("caps a driver's trail at MAX_TRAIL_POINTS_PER_DRIVER, dropping the oldest points", () => {
    const { result } = renderHook(() => usePositionPlayback());
    const manySamples = Array.from({ length: 2010 }, (_, i) => sample(i, i, "2026-01-01T00:00:00.000Z"));

    act(() => {
      result.current.feedBatch({ "44": manySamples });
    });

    const trail = result.current.trailRef.current["44"];
    expect(trail).toHaveLength(2000);
    // The oldest 10 points (x=0..9) should have been dropped, leaving x=10 first.
    expect(trail[0]).toEqual({ x: 10, y: 10 });
    expect(trail[trail.length - 1]).toEqual({ x: 2009, y: 2009 });
  });

  it("ignores an empty sample list for a driver", () => {
    const { result } = renderHook(() => usePositionPlayback());

    act(() => {
      result.current.feedBatch({ "44": [] });
    });

    expect(result.current.trailRef.current["44"]).toBeUndefined();
  });

  it("reset clears positions, trails, and in-flight playback", () => {
    const { result } = renderHook(() => usePositionPlayback());
    act(() => {
      result.current.feedBatch({ "44": [sample(0, 0, "2026-01-01T00:00:00.000Z")] });
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.positionsRef.current).toEqual({});
    expect(result.current.trailRef.current).toEqual({});
  });
});
