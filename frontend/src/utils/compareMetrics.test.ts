import { describe, expect, it } from "vitest";
import {
  addDriverEvent,
  DriverEventMarker,
  extractPenaltyDriverNumber,
  formatMetricValue,
  formatPenaltyLabel,
  formatPitStopLabel,
  formatTyreChangeLabel,
  isDiscreteMetric,
  isPenaltyMessage,
  parseTimeToSeconds,
  sectorIndexForMetric,
  titleCaseCompound,
  tukeyFences,
  upsertLapMetricPoint,
  LapMetricPoint,
} from "./compareMetrics";

describe("parseTimeToSeconds", () => {
  it("parses a lap-time formatted string (M:SS.mmm)", () => {
    expect(parseTimeToSeconds("1:24.840")).toBeCloseTo(84.84);
  });

  it("parses a plain sector-time formatted string (SS.mmm)", () => {
    expect(parseTimeToSeconds("28.924")).toBeCloseTo(28.924);
  });

  it("parses a multi-minute lap time", () => {
    expect(parseTimeToSeconds("2:03.501")).toBeCloseTo(123.501);
  });

  it("returns null for an empty string", () => {
    expect(parseTimeToSeconds("")).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(parseTimeToSeconds(undefined)).toBeNull();
  });

  it("returns null for unparseable garbage input", () => {
    expect(parseTimeToSeconds("not-a-time")).toBeNull();
    expect(parseTimeToSeconds("abc:def")).toBeNull();
  });
});

describe("isDiscreteMetric", () => {
  it("is true for the four per-lap metrics", () => {
    expect(isDiscreteMetric("sector1")).toBe(true);
    expect(isDiscreteMetric("sector2")).toBe(true);
    expect(isDiscreteMetric("sector3")).toBe(true);
    expect(isDiscreteMetric("lapTime")).toBe(true);
  });

  it("is false for the three continuous telemetry metrics", () => {
    expect(isDiscreteMetric("speed")).toBe(false);
    expect(isDiscreteMetric("throttle")).toBe(false);
    expect(isDiscreteMetric("brake")).toBe(false);
  });
});

describe("sectorIndexForMetric", () => {
  it("maps sector1/2/3 to Sectors keys 0/1/2", () => {
    expect(sectorIndexForMetric("sector1")).toBe("0");
    expect(sectorIndexForMetric("sector2")).toBe("1");
    expect(sectorIndexForMetric("sector3")).toBe("2");
  });

  it("returns null for lapTime (reads LastLapTime instead)", () => {
    expect(sectorIndexForMetric("lapTime")).toBeNull();
  });
});

describe("upsertLapMetricPoint", () => {
  it("inserts a fresh point for a driver with no history yet", () => {
    const history: Record<number, LapMetricPoint[]> = {};
    upsertLapMetricPoint(history, 44, 3, 28.5);
    expect(history[44]).toEqual([{ lap: 3, value: 28.5 }]);
  });

  it("overwrites the value for an existing lap rather than duplicating it", () => {
    const history: Record<number, LapMetricPoint[]> = { 44: [{ lap: 3, value: 28.5 }] };
    upsertLapMetricPoint(history, 44, 3, 27.9);
    expect(history[44]).toEqual([{ lap: 3, value: 27.9 }]);
  });

  it("appends a new lap in order when it arrives after existing laps", () => {
    const history: Record<number, LapMetricPoint[]> = { 44: [{ lap: 3, value: 28.5 }] };
    upsertLapMetricPoint(history, 44, 4, 28.1);
    expect(history[44]).toEqual([
      { lap: 3, value: 28.5 },
      { lap: 4, value: 28.1 },
    ]);
  });

  it("inserts an out-of-order lap and keeps the array sorted ascending by lap", () => {
    const history: Record<number, LapMetricPoint[]> = {
      44: [
        { lap: 1, value: 29.0 },
        { lap: 3, value: 28.5 },
      ],
    };
    upsertLapMetricPoint(history, 44, 2, 28.8);
    expect(history[44]).toEqual([
      { lap: 1, value: 29.0 },
      { lap: 2, value: 28.8 },
      { lap: 3, value: 28.5 },
    ]);
  });

  it("keeps independent drivers' histories from clobbering each other", () => {
    const history: Record<number, LapMetricPoint[]> = {};
    upsertLapMetricPoint(history, 44, 1, 29.0);
    upsertLapMetricPoint(history, 16, 1, 28.2);
    upsertLapMetricPoint(history, 44, 2, 28.9);
    expect(history[44]).toEqual([
      { lap: 1, value: 29.0 },
      { lap: 2, value: 28.9 },
    ]);
    expect(history[16]).toEqual([{ lap: 1, value: 28.2 }]);
  });
});

describe("addDriverEvent", () => {
  it("adds a fresh event for a driver with no history yet", () => {
    const events: Record<number, DriverEventMarker[]> = {};
    addDriverEvent(events, 44, { lap: 3, kind: "pit", label: "Pit stop (lap 3)" });
    expect(events[44]).toEqual([{ lap: 3, kind: "pit", label: "Pit stop (lap 3)" }]);
  });

  it("appends a second, distinct event for the same driver", () => {
    const events: Record<number, DriverEventMarker[]> = {};
    addDriverEvent(events, 44, { lap: 3, kind: "pit", label: "Pit stop (lap 3)" });
    addDriverEvent(events, 44, { lap: 10, kind: "pit", label: "Pit stop (lap 10)" });
    expect(events[44]).toHaveLength(2);
  });

  it("does not duplicate an identical (lap, kind, label) triple re-fired by a resend", () => {
    const events: Record<number, DriverEventMarker[]> = {};
    addDriverEvent(events, 44, { lap: 3, kind: "pit", label: "Pit stop (lap 3)" });
    addDriverEvent(events, 44, { lap: 3, kind: "pit", label: "Pit stop (lap 3)" });
    expect(events[44]).toHaveLength(1);
  });

  it("keeps independent drivers' event lists from clobbering each other", () => {
    const events: Record<number, DriverEventMarker[]> = {};
    addDriverEvent(events, 44, { lap: 3, kind: "pit", label: "Pit stop (lap 3)" });
    addDriverEvent(events, 16, { lap: 3, kind: "tyre", label: "Pitted for Medium (lap 3)" });
    expect(events[44]).toHaveLength(1);
    expect(events[16]).toHaveLength(1);
  });
});

describe("tukeyFences", () => {
  it("returns null when there are fewer than MIN_SAMPLE_FOR_OUTLIER_FENCES values", () => {
    expect(tukeyFences([29.1, 29.3, 29.4, 29.5])).toBeNull();
  });

  it("returns null when the IQR is 0 (every value identical so far)", () => {
    expect(tukeyFences([30, 30, 30, 30, 30])).toBeNull();
  });

  it("computes the standard [Q1 - 1.5*IQR, Q3 + 1.5*IQR] fences", () => {
    const values = [29.1, 29.3, 29.4, 29.5, 29.6, 29.8, 30.0];
    const fences = tukeyFences(values);
    expect(fences).not.toBeNull();
    // Q1=29.35, Q3=29.7, IQR=0.35 (linear-interpolation quantile convention)
    expect(fences!.lower).toBeCloseTo(28.825);
    expect(fences!.upper).toBeCloseTo(30.225);
  });

  it("flags a pit-stop-magnitude spike as outside the fences", () => {
    const values = [29.1, 29.3, 29.4, 29.5, 29.6, 29.8, 30.0, 48.2];
    const fences = tukeyFences(values);
    expect(fences).not.toBeNull();
    expect(48.2).toBeGreaterThan(fences!.upper);
  });

  it("does NOT flag ordinary racing-pace variance as outside the fences", () => {
    const values = [29.1, 29.3, 29.4, 29.5, 29.6, 29.8, 30.0, 30.2];
    const fences = tukeyFences(values);
    expect(fences).not.toBeNull();
    expect(30.2).toBeLessThan(fences!.upper);
  });
});

describe("formatMetricValue", () => {
  it("formats sector times as plain seconds", () => {
    expect(formatMetricValue("sector1", 28.924)).toBe("28.924");
  });

  it("formats lap times as M:SS.mmm", () => {
    expect(formatMetricValue("lapTime", 84.84)).toBe("1:24.840");
  });

  it("pads sub-10-second lap-time remainders", () => {
    expect(formatMetricValue("lapTime", 65.004)).toBe("1:05.004");
  });
});

describe("formatPitStopLabel", () => {
  it("formats the lap number into the label", () => {
    expect(formatPitStopLabel(12)).toBe("Pit stop (lap 12)");
  });
});

describe("titleCaseCompound", () => {
  it("title-cases an all-caps compound", () => {
    expect(titleCaseCompound("MEDIUM")).toBe("Medium");
  });

  it("title-cases a lowercase compound", () => {
    expect(titleCaseCompound("soft")).toBe("Soft");
  });

  it("passes through an empty string unchanged", () => {
    expect(titleCaseCompound("")).toBe("");
  });
});

describe("formatTyreChangeLabel", () => {
  it("formats compound and lap into the label", () => {
    expect(formatTyreChangeLabel("MEDIUM", 12)).toBe("Pitted for Medium (lap 12)");
  });
});

describe("isPenaltyMessage", () => {
  it("matches a real FIA penalty message, case-insensitively", () => {
    expect(
      isPenaltyMessage("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) - CAUSING A COLLISION (15:57:04)")
    ).toBe(true);
    expect(isPenaltyMessage("fia stewards: 5 second time penalty for car 55")).toBe(true);
  });

  it("does not match an unrelated race control message", () => {
    expect(isPenaltyMessage("GREEN LIGHT - PIT EXIT OPEN")).toBe(false);
    expect(isPenaltyMessage("CHEQUERED FLAG")).toBe(false);
  });
});

describe("extractPenaltyDriverNumber", () => {
  it("extracts the car number from a real penalty message", () => {
    expect(
      extractPenaltyDriverNumber(
        "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) - CAUSING A COLLISION (15:57:04)"
      )
    ).toBe(55);
  });

  it("returns null when no car number is present", () => {
    expect(extractPenaltyDriverNumber("FIA STEWARDS: UNDER INVESTIGATION")).toBeNull();
  });

  it("returns null for a matched number so large it overflows to a non-finite value", () => {
    expect(extractPenaltyDriverNumber(`CAR ${"9".repeat(400)}`)).toBeNull();
  });
});

describe("formatPenaltyLabel", () => {
  it("returns a short message unchanged (trimmed)", () => {
    expect(formatPenaltyLabel("  5 SECOND PENALTY FOR CAR 55  ")).toBe("5 SECOND PENALTY FOR CAR 55");
  });

  it("truncates a very long message with an ellipsis", () => {
    const long = "PENALTY " + "X".repeat(200);
    const result = formatPenaltyLabel(long);
    expect(result.length).toBeLessThan(long.length);
    expect(result.endsWith("…")).toBe(true);
  });
});
