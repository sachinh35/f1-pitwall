import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CompareWidget from "./CompareWidget";
import {
  clampedLapPointToCanvas,
  computeLapValueBounds,
  detectLapBoundaryIndices,
  findLapTagIndex,
  lapLabelStep,
  lapPointToCanvas,
  scaleToBand,
} from "./compareWidgetMath";
import { DiscreteCompareMetric, DriverEventMarker, LapMetricPoint } from "../../utils/compareMetrics";
import { TelemetrySample } from "../../types/raceMode";

describe("scaleToBand", () => {
  it("maps a zero value to the bottom of the band", () => {
    expect(scaleToBand(0, 100, 0, 60)).toBe(60);
  });

  it("maps a value equal to domainMax to the top of the band", () => {
    expect(scaleToBand(100, 100, 0, 60)).toBe(0);
  });

  it("maps a mid-range value to the vertical midpoint of the band", () => {
    expect(scaleToBand(50, 100, 0, 60)).toBe(30);
  });

  it("offsets by bandTop for bands not starting at y=0", () => {
    expect(scaleToBand(0, 100, 82, 60)).toBe(142);
    expect(scaleToBand(100, 100, 82, 60)).toBe(82);
  });
});

describe("lapPointToCanvas", () => {
  const bounds = { minLap: 1, maxLap: 11, minValue: 20, maxValue: 30 };

  it("maps the (minLap, minValue) corner to the bottom-left, inside padding", () => {
    const { x, y } = lapPointToCanvas(1, 20, bounds, 100, 50, 10);
    expect(x).toBe(10);
    expect(y).toBe(40);
  });

  it("maps the (maxLap, maxValue) corner to the top-right, inside padding", () => {
    const { x, y } = lapPointToCanvas(11, 30, bounds, 100, 50, 10);
    expect(x).toBe(90);
    expect(y).toBe(10);
  });

  it("maps the midpoint to the center of the plotting area", () => {
    const { x, y } = lapPointToCanvas(6, 25, bounds, 100, 50, 10);
    expect(x).toBe(50);
    expect(y).toBe(25);
  });

  it("does not divide by zero for a degenerate (single-lap) lap domain", () => {
    const degenerate = { minLap: 5, maxLap: 5, minValue: 20, maxValue: 30 };
    const { x } = lapPointToCanvas(5, 25, degenerate, 100, 50, 10);
    expect(Number.isFinite(x)).toBe(true);
    expect(x).toBe(10);
  });

  it("does not divide by zero for a degenerate (single-value) value domain", () => {
    const degenerate = { minLap: 1, maxLap: 11, minValue: 25, maxValue: 25 };
    const { y } = lapPointToCanvas(6, 25, degenerate, 100, 50, 10);
    expect(Number.isFinite(y)).toBe(true);
    expect(y).toBe(40);
  });
});

const emptyTelemetryRef = { current: {} as Record<string, TelemetrySample> };
const emptyHistoryRef = {
  current: {
    sector1: {},
    sector2: {},
    sector3: {},
    lapTime: {},
  } as Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>,
};
const emptyCurrentLapRef = { current: {} as Record<number, number> };
const emptyDriverEventsRef = { current: {} as Record<number, DriverEventMarker[]> };

function renderWidget(overrides: Partial<React.ComponentProps<typeof CompareWidget>> = {}) {
  const onMetricChange = vi.fn();
  const onRemove = vi.fn();
  const utils = render(
    <CompareWidget
      metric="speed"
      onMetricChange={onMetricChange}
      onRemove={onRemove}
      selectedDrivers={[]}
      telemetryRef={emptyTelemetryRef}
      lapMetricHistoryRef={emptyHistoryRef}
      currentLapRef={emptyCurrentLapRef}
      driverEventsRef={emptyDriverEventsRef}
      {...overrides}
    />
  );
  return { ...utils, onMetricChange, onRemove };
}

describe("CompareWidget", () => {
  it("renders a canvas", () => {
    const { container } = renderWidget();
    expect(container.querySelector("canvas.rm-compare-canvas")).not.toBeNull();
  });

  it("lists exactly the 7 metrics in the specified order", () => {
    renderWidget();
    const options = screen.getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(["speed", "throttle", "brake", "sector1", "sector2", "sector3", "lapTime"]);
  });

  it("calls onMetricChange with the newly selected metric", () => {
    const { onMetricChange } = renderWidget();
    fireEvent.change(screen.getByLabelText("Comparison metric"), { target: { value: "sector2" } });
    expect(onMetricChange).toHaveBeenCalledWith("sector2");
  });

  it("calls onRemove when the remove button is clicked", () => {
    const { onRemove } = renderWidget();
    fireEvent.click(screen.getByTitle("Remove this comparison widget"));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("renders one legend entry per selected driver (up to 4) with the right TLA", () => {
    renderWidget({ selectedDrivers: [3, 16, 44, 63, 1] });
    expect(screen.getByText("VER")).toBeInTheDocument();
    expect(screen.getByText("LEC")).toBeInTheDocument();
    expect(screen.getByText("HAM")).toBeInTheDocument();
    expect(screen.getByText("RUS")).toBeInTheDocument();
    // 5th selected driver is not rendered - widgets cap at 4
    expect(screen.queryByText("NOR")).not.toBeInTheDocument();
  });

  it("renders no legend entries when no drivers are selected", () => {
    const { container } = renderWidget({ selectedDrivers: [] });
    expect(container.querySelector(".rm-telemetry-legend")?.children.length).toBe(0);
  });
});

describe("detectLapBoundaryIndices", () => {
  it("returns an empty array for an empty input", () => {
    expect(detectLapBoundaryIndices([], -1)).toEqual([]);
  });

  it("returns an empty array when the tag never changes", () => {
    expect(detectLapBoundaryIndices([3, 3, 3, 3], -1)).toEqual([]);
  });

  it("detects a single lap-boundary crossing", () => {
    expect(detectLapBoundaryIndices([3, 3, 4, 4], -1)).toEqual([2]);
  });

  it("detects multiple lap-boundary crossings", () => {
    expect(detectLapBoundaryIndices([3, 3, 4, 4, 4, 5], -1)).toEqual([2, 5]);
  });

  it("ignores a leading run of the unknown sentinel", () => {
    expect(detectLapBoundaryIndices([-1, -1, 3, 3, 4], -1)).toEqual([4]);
  });

  it("ignores a trailing run of the unknown sentinel", () => {
    expect(detectLapBoundaryIndices([3, 3, 4, -1, -1], -1)).toEqual([2]);
  });

  it("does not treat a sentinel value itself as a boundary", () => {
    expect(detectLapBoundaryIndices([3, -1, 3, 4], -1)).toEqual([3]);
  });
});

describe("findLapTagIndex", () => {
  it("finds the exact matching lap", () => {
    expect(findLapTagIndex([3, 3, 4, 4, 5], 4, -1)).toBe(2);
  });

  it("returns null when no tag is within tolerance", () => {
    expect(findLapTagIndex([3, 3, 4, 4, 5], 40, -1)).toBeNull();
  });

  it("falls back to the closest tag within tolerance when there's no exact match", () => {
    // lap 6 isn't tagged anywhere, but 5 (index 4) is within the default tolerance of 1
    expect(findLapTagIndex([3, 3, 4, 4, 5], 6, -1)).toBe(4);
  });

  it("skips unknown-sentinel entries when searching", () => {
    expect(findLapTagIndex([-1, -1, 4, 4], 4, -1)).toBe(2);
  });

  it("returns null for an all-unknown array", () => {
    expect(findLapTagIndex([-1, -1, -1], 4, -1)).toBeNull();
  });
});

describe("computeLapValueBounds", () => {
  it("returns null when no selected driver has any points", () => {
    expect(computeLapValueBounds({}, [44, 16])).toBeNull();
  });

  it("computes lap/value bounds (with a small value padding) across selected drivers", () => {
    const history: Record<number, LapMetricPoint[]> = {
      44: [
        { lap: 1, value: 28 },
        { lap: 3, value: 30 },
      ],
      16: [{ lap: 2, value: 26 }],
    };
    const bounds = computeLapValueBounds(history, [44, 16]);
    expect(bounds).not.toBeNull();
    expect(bounds!.minLap).toBe(1);
    expect(bounds!.maxLap).toBe(3);
    // value padding is 5% of the observed span (30 - 26 = 4) on each side
    expect(bounds!.minValue).toBeCloseTo(25.8);
    expect(bounds!.maxValue).toBeCloseTo(30.2);
  });

  it("ignores drivers not in the selected list", () => {
    const history: Record<number, LapMetricPoint[]> = {
      44: [{ lap: 1, value: 28 }],
      99: [{ lap: 50, value: 100 }],
    };
    const bounds = computeLapValueBounds(history, [44]);
    expect(bounds!.maxLap).toBe(1);
  });

  it("excludes a statistical outlier's value from the scale, but keeps it in the lap range", () => {
    const history: Record<number, LapMetricPoint[]> = {
      44: [
        { lap: 1, value: 28.0 },
        { lap: 2, value: 27.5 },
        { lap: 3, value: 46.2 }, // pit lane transit - a huge outlier
        { lap: 4, value: 27.9 },
        { lap: 5, value: 27.7 },
        { lap: 6, value: 28.1 },
        { lap: 7, value: 27.6 },
      ],
    };
    const bounds = computeLapValueBounds(history, [44]);
    expect(bounds!.minLap).toBe(1);
    expect(bounds!.maxLap).toBe(7); // the outlier lap still counts for the X range
    // value range comes only from the 6 clustered laps (27.5-28.1) - 46.2 never touches it
    expect(bounds!.maxValue).toBeLessThan(30);
  });

  it("does not filter anything below the minimum sample size - not enough data yet to tell a " +
    "genuine outlier from ordinary early-race noise, so a spike still widens the scale", () => {
    const history: Record<number, LapMetricPoint[]> = {
      44: [
        { lap: 1, value: 28 },
        { lap: 2, value: 27.5 },
        { lap: 3, value: 46.2 }, // only 3 points total - below MIN_SAMPLE_FOR_OUTLIER_FENCES
      ],
    };
    const bounds = computeLapValueBounds(history, [44]);
    expect(bounds!.maxValue).toBeGreaterThan(40);
  });

  it("computes each driver's outlier fences from their own history independently", () => {
    const history: Record<number, LapMetricPoint[]> = {
      // driver 44: tight, fast pace with one pit-stop outlier
      44: [
        { lap: 1, value: 28.0 },
        { lap: 2, value: 27.5 },
        { lap: 3, value: 27.9 },
        { lap: 4, value: 27.7 },
        { lap: 5, value: 28.1 },
        { lap: 6, value: 46.2 },
      ],
      // driver 16: consistently slower pace, but with no outliers of their own
      16: [
        { lap: 1, value: 33.0 },
        { lap: 2, value: 32.5 },
        { lap: 3, value: 32.9 },
        { lap: 4, value: 32.7 },
        { lap: 5, value: 33.1 },
      ],
    };
    const bounds = computeLapValueBounds(history, [44, 16]);
    // driver 16's genuinely-slower-but-normal pace should still set the top of the range
    expect(bounds!.maxValue).toBeGreaterThan(33);
    expect(bounds!.maxValue).toBeLessThan(40);
  });
});

describe("clampedLapPointToCanvas", () => {
  const bounds = { minLap: 1, maxLap: 5, minValue: 20, maxValue: 30 };

  it("does not clamp a point within the value range", () => {
    const result = clampedLapPointToCanvas({ lap: 3, value: 25 }, bounds, 100, 50, 10);
    expect(result.isOffScale).toBe(false);
    expect(result).toMatchObject(lapPointToCanvas(3, 25, bounds, 100, 50, 10));
  });

  it("clamps a point above maxValue to the top edge and flags it off-scale", () => {
    const result = clampedLapPointToCanvas({ lap: 3, value: 46.2 }, bounds, 100, 50, 10);
    expect(result.isOffScale).toBe(true);
    expect(result).toMatchObject(lapPointToCanvas(3, bounds.maxValue, bounds, 100, 50, 10));
  });

  it("clamps a point below minValue to the bottom edge and flags it off-scale", () => {
    const result = clampedLapPointToCanvas({ lap: 3, value: 5 }, bounds, 100, 50, 10);
    expect(result.isOffScale).toBe(true);
    expect(result).toMatchObject(lapPointToCanvas(3, bounds.minValue, bounds, 100, 50, 10));
  });
});

describe("lapLabelStep", () => {
  it("labels every lap when the span is small", () => {
    expect(lapLabelStep(0)).toBe(1);
    expect(lapLabelStep(5)).toBe(1);
    expect(lapLabelStep(12)).toBe(1);
  });

  it("thins out labels once the span exceeds 12 laps, keeping roughly 12 on screen", () => {
    expect(lapLabelStep(13)).toBe(2);
    expect(lapLabelStep(24)).toBe(2);
    expect(lapLabelStep(60)).toBe(5);
  });
});

describe("CompareWidget event markers", () => {
  it("renders a DOM marker combining the lap's value and the event's label when a pit/tyre/penalty event lands on a plotted lap", async () => {
    const lapMetricHistoryRef = {
      current: {
        sector1: {
          44: [
            { lap: 1, value: 28 },
            { lap: 2, value: 27.5 },
            { lap: 5, value: 27.8 },
          ],
        },
        sector2: {},
        sector3: {},
        lapTime: {},
      } as Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>,
    };
    const driverEventsRef = {
      current: {
        44: [{ lap: 2, kind: "pit", label: "Pit stop (lap 2)" }] as DriverEventMarker[],
      },
    };

    renderWidget({
      metric: "sector1",
      selectedDrivers: [44],
      lapMetricHistoryRef,
      driverEventsRef,
    });

    await waitFor(() => expect(screen.getByText("P")).toBeInTheDocument());
    expect(screen.getByText("P").title).toBe("HAM · Lap 2: 27.500\nPit stop (lap 2)");
  });

  it("renders a hoverable marker with just the lap's value when no event happened on that lap", async () => {
    const lapMetricHistoryRef = {
      current: {
        sector1: {
          44: [{ lap: 1, value: 28 }],
        },
        sector2: {},
        sector3: {},
        lapTime: {},
      } as Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>,
    };
    const driverEventsRef = { current: {} };

    renderWidget({
      metric: "sector1",
      selectedDrivers: [44],
      lapMetricHistoryRef,
      driverEventsRef,
    });

    await waitFor(() => expect(screen.getByTitle("HAM · Lap 1: 28.000")).toBeInTheDocument());
  });

  it("does not render a marker for an event whose lap has no corresponding plotted point in the current metric/domain", async () => {
    const lapMetricHistoryRef = {
      current: {
        sector1: {
          44: [
            { lap: 1, value: 28 },
            { lap: 2, value: 27.5 },
            { lap: 5, value: 27.8 },
          ],
        },
        sector2: {},
        sector3: {},
        lapTime: {},
      } as Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>,
    };
    const driverEventsRef = {
      current: {
        44: [{ lap: 40, kind: "penalty", label: "5 SECOND PENALTY FOR CAR 44" }] as DriverEventMarker[],
      },
    };

    renderWidget({
      metric: "sector1",
      selectedDrivers: [44],
      lapMetricHistoryRef,
      driverEventsRef,
    });

    await waitFor(() => expect(screen.getByTitle("HAM · Lap 1: 28.000")).toBeInTheDocument());
    expect(screen.queryByTitle(/5 SECOND PENALTY/)).not.toBeInTheDocument();
  });
});
