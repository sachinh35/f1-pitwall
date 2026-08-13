import { describe, expect, it } from "vitest";
import { formatDuration, formatLapDuration } from "./formatting";

describe("formatDuration", () => {
  it("returns an empty string for null", () => {
    expect(formatDuration(null)).toBe("");
  });

  it("returns an empty string for a string input", () => {
    expect(formatDuration("not-a-number")).toBe("");
  });

  it("formats a sub-minute duration with zero-padded minutes/seconds and 3-digit millis", () => {
    expect(formatDuration(5.123)).toBe("0:00:05.123");
  });

  it("formats a duration spanning minutes", () => {
    expect(formatDuration(75.5)).toBe("0:01:15.500");
  });

  it("formats a duration spanning hours", () => {
    expect(formatDuration(3661.25)).toBe("1:01:01.250");
  });

  it("formats exactly zero", () => {
    expect(formatDuration(0)).toBe("0:00:00.000");
  });
});

describe("formatLapDuration", () => {
  it("returns an empty string for null", () => {
    // @ts-expect-error - exercising the runtime null guard despite the narrower type
    expect(formatLapDuration(null)).toBe("");
  });

  it("returns an empty string for undefined", () => {
    // @ts-expect-error - exercising the runtime undefined guard despite the narrower type
    expect(formatLapDuration(undefined)).toBe("");
  });

  it("formats a sub-minute value with zero-padded seconds", () => {
    expect(formatLapDuration(5.5)).toBe("0:05.500");
  });

  it("formats a value spanning minutes", () => {
    expect(formatLapDuration(83.123)).toBe("1:23.123");
  });

  it("formats exactly zero", () => {
    expect(formatLapDuration(0)).toBe("0:00.000");
  });
});
