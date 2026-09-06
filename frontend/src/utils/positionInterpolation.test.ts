import { describe, expect, it } from "vitest";
import { interpolatePositionAtTime } from "./positionInterpolation";
import { PositionSample } from "../types/raceMode";

function sample(x: number, y: number, utc?: string): PositionSample {
  return { x, y, z: 0, status: "OnTrack", utc };
}

const T0 = Date.parse("2026-01-01T00:00:00.000Z");
const T1 = Date.parse("2026-01-01T00:00:00.500Z");
const T2 = Date.parse("2026-01-01T00:00:01.000Z");

describe("interpolatePositionAtTime", () => {
  const samples = [
    sample(0, 0, "2026-01-01T00:00:00.000Z"),
    sample(10, 20, "2026-01-01T00:00:00.500Z"),
    sample(20, 40, "2026-01-01T00:00:01.000Z"),
  ];

  it("returns the first sample at its own timestamp", () => {
    expect(interpolatePositionAtTime(samples, T0)).toEqual({ x: 0, y: 0, z: 0, status: "OnTrack" });
  });

  it("returns the last sample at its own timestamp", () => {
    expect(interpolatePositionAtTime(samples, T2)).toEqual({ x: 20, y: 40, z: 0, status: "OnTrack" });
  });

  it("returns an exact intermediate sample when now lands on it", () => {
    expect(interpolatePositionAtTime(samples, T1)).toEqual({ x: 10, y: 20, z: 0, status: "OnTrack" });
  });

  it("interpolates between the two real samples straddling now", () => {
    const midOfFirstSegment = T0 + (T1 - T0) / 2;
    expect(interpolatePositionAtTime(samples, midOfFirstSegment)).toEqual({ x: 5, y: 10, z: 0, status: "OnTrack" });
  });

  it("interpolates within the second segment, not just the overall endpoints", () => {
    const threeQuarters = T1 + (T2 - T1) * 0.5;
    expect(interpolatePositionAtTime(samples, threeQuarters)).toEqual({ x: 15, y: 30, z: 0, status: "OnTrack" });
  });

  it("clamps to the first sample for a time before the batch starts", () => {
    expect(interpolatePositionAtTime(samples, T0 - 5000)).toEqual({ x: 0, y: 0, z: 0, status: "OnTrack" });
  });

  it("clamps to the last sample for a time after the batch ends", () => {
    expect(interpolatePositionAtTime(samples, T2 + 5000)).toEqual({ x: 20, y: 40, z: 0, status: "OnTrack" });
  });

  it("returns the only sample for a single-sample batch, regardless of time", () => {
    expect(interpolatePositionAtTime([sample(5, 5, "2026-01-01T00:00:00.000Z")], T2)).toEqual({
      x: 5,
      y: 5,
      z: 0,
      status: "OnTrack",
    });
  });

  it("falls back to the last sample when a timestamp is missing", () => {
    const withMissingUtc = [sample(0, 0), sample(10, 10, "2026-01-01T00:00:01.000Z")];
    expect(interpolatePositionAtTime(withMissingUtc, T0)).toEqual({ x: 10, y: 10, z: 0, status: "OnTrack" });
  });

  it("falls back to the last sample when a timestamp is unparseable", () => {
    const withBadUtc = [sample(0, 0, "not-a-date"), sample(10, 10, "2026-01-01T00:00:01.000Z")];
    expect(interpolatePositionAtTime(withBadUtc, T0)).toEqual({ x: 10, y: 10, z: 0, status: "OnTrack" });
  });

  it("uses the later sample's status once past its timestamp", () => {
    const withStatus = [
      sample(0, 0, "2026-01-01T00:00:00.000Z"),
      { x: 10, y: 10, z: 0, status: "OFF_TRACK", utc: "2026-01-01T00:00:01.000Z" },
    ];
    expect(interpolatePositionAtTime(withStatus, T2).status).toBe("OFF_TRACK");
  });
});
