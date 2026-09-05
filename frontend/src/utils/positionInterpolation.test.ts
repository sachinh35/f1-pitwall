import { describe, expect, it } from "vitest";
import { computeBatchDurationMs, interpolatePositionSample } from "./positionInterpolation";
import { PositionSample } from "../types/raceMode";

function sample(x: number, y: number, utc?: string): PositionSample {
  return { x, y, z: 0, status: "OnTrack", utc };
}

describe("computeBatchDurationMs", () => {
  it("returns the real time span between the first and last sample", () => {
    const samples = [
      sample(0, 0, "2026-01-01T00:00:00.000Z"),
      sample(1, 1, "2026-01-01T00:00:00.500Z"),
      sample(2, 2, "2026-01-01T00:00:01.000Z"),
    ];
    expect(computeBatchDurationMs(samples)).toBe(1000);
  });

  it("returns 0 for an empty batch", () => {
    expect(computeBatchDurationMs([])).toBe(0);
  });

  it("returns 0 for a single-sample batch", () => {
    expect(computeBatchDurationMs([sample(0, 0, "2026-01-01T00:00:00.000Z")])).toBe(0);
  });

  it("returns 0 when a timestamp is missing", () => {
    expect(computeBatchDurationMs([sample(0, 0), sample(1, 1, "2026-01-01T00:00:01.000Z")])).toBe(0);
  });

  it("returns 0 when a timestamp is unparseable", () => {
    expect(computeBatchDurationMs([sample(0, 0, "not-a-date"), sample(1, 1, "2026-01-01T00:00:01.000Z")])).toBe(0);
  });
});

describe("interpolatePositionSample", () => {
  const samples = [sample(0, 0), sample(10, 20), sample(20, 40)];

  it("returns the first sample at elapsed=0", () => {
    expect(interpolatePositionSample(samples, 0, 1000)).toEqual({ x: 0, y: 0, z: 0, status: "OnTrack" });
  });

  it("returns the last sample once elapsed reaches the full duration", () => {
    expect(interpolatePositionSample(samples, 1000, 1000)).toEqual({ x: 20, y: 40, z: 0, status: "OnTrack" });
  });

  it("interpolates between the two real samples straddling the midpoint", () => {
    // Halfway through 3 evenly-spaced samples lands exactly on the middle one.
    expect(interpolatePositionSample(samples, 500, 1000)).toEqual({ x: 10, y: 20, z: 0, status: "OnTrack" });
  });

  it("interpolates between intermediate samples, not just the endpoints", () => {
    // 3/4 of the way through 3 samples (2 segments) is halfway through the second segment.
    expect(interpolatePositionSample(samples, 750, 1000)).toEqual({ x: 15, y: 30, z: 0, status: "OnTrack" });
  });

  it("clamps elapsed beyond the duration to the last sample", () => {
    expect(interpolatePositionSample(samples, 5000, 1000)).toEqual({ x: 20, y: 40, z: 0, status: "OnTrack" });
  });

  it("clamps negative elapsed to the first sample", () => {
    expect(interpolatePositionSample(samples, -100, 1000)).toEqual({ x: 0, y: 0, z: 0, status: "OnTrack" });
  });

  it("always returns the last sample when duration is 0", () => {
    expect(interpolatePositionSample(samples, 0, 0)).toEqual({ x: 20, y: 40, z: 0, status: "OnTrack" });
  });

  it("returns the only sample for a single-sample batch", () => {
    expect(interpolatePositionSample([sample(5, 5)], 0, 0)).toEqual({ x: 5, y: 5, z: 0, status: "OnTrack" });
  });

  it("uses the later sample's status once past its midpoint", () => {
    const withStatus = [
      { x: 0, y: 0, z: 0, status: "OnTrack" },
      { x: 10, y: 10, z: 0, status: "OFF_TRACK" },
    ];
    expect(interpolatePositionSample(withStatus, 600, 1000).status).toBe("OFF_TRACK");
  });
});
