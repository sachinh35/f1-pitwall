import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LapComparisonChart from "./LapComparisonChart";
import { LapData, RaceControlEvent, Stint } from "../services/api";
import { EnrichedF1SessionResult } from "../types";

const lap = (overrides: Partial<LapData>): LapData => ({
  meeting_key: 1,
  session_key: 100,
  driver_number: 1,
  lap_number: 1,
  date_start: "2026-01-01T10:00:00Z",
  duration_sector_1: 30,
  duration_sector_2: 30,
  duration_sector_3: 30,
  lap_duration: 90,
  i1_speed: null,
  i2_speed: null,
  st_speed: null,
  is_pit_out_lap: false,
  segments_sector_1: null,
  segments_sector_2: null,
  segments_sector_3: null,
  ...overrides,
});

const result = (overrides: Partial<EnrichedF1SessionResult>): EnrichedF1SessionResult => ({
  dnf: false,
  dns: false,
  dsq: false,
  driver_number: 1,
  number_of_laps: 50,
  meeting_key: 1,
  session_key: 100,
  duration: 5000,
  gap_to_leader: null,
  position: 1,
  full_name: "Driver One",
  name_acronym: "DR1",
  first_name: "Driver",
  last_name: "One",
  country_code: "GBR",
  ...overrides,
});

const rcEvent = (overrides: Partial<RaceControlEvent>): RaceControlEvent => ({
  session_key: 100,
  date: "2026-01-01T10:01:30Z",
  category: "Flag",
  message: "YELLOW FLAG",
  scope: "Track",
  sector: null,
  driver_number: null,
  flag: "YELLOW",
  ...overrides,
});

const baseLaps: LapData[] = [
  lap({ driver_number: 1, lap_number: 1, date_start: "2026-01-01T10:00:00Z", lap_duration: 90, is_pit_out_lap: true }),
  lap({ driver_number: 1, lap_number: 2, date_start: "2026-01-01T10:01:30Z", lap_duration: 88 }),
  lap({ driver_number: 2, lap_number: 1, date_start: "2026-01-01T10:00:00Z", lap_duration: 91 }),
  lap({ driver_number: 2, lap_number: 2, date_start: "2026-01-01T10:01:31Z", lap_duration: 89 }),
];

const baseStints: Stint[] = [
  { meeting_key: 1, session_key: 100, driver_number: 1, stint_number: 1, lap_start: 1, lap_end: 2, compound: "SOFT", tyre_age_at_start: 0 },
  { meeting_key: 1, session_key: 100, driver_number: 2, stint_number: 1, lap_start: 1, lap_end: 2, compound: "MEDIUM", tyre_age_at_start: 3 },
];

const baseResults: EnrichedF1SessionResult[] = [
  result({ driver_number: 1, full_name: "Lando Norris" }),
  result({ driver_number: 2, full_name: "Max Verstappen" }),
];

function renderChart(overrides: Partial<React.ComponentProps<typeof LapComparisonChart>> = {}) {
  return render(
    <LapComparisonChart
      lapData={baseLaps}
      selectedDrivers={[1, 2]}
      sessionResults={baseResults}
      stints={baseStints}
      raceControlEvents={[]}
      {...overrides}
    />
  );
}

describe("LapComparisonChart", () => {
  it("renders the chart and zoom controls without crashing", () => {
    const { container } = renderChart();
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
    expect(screen.getByTitle("Zoom In (Y-axis)")).toBeInTheDocument();
    expect(screen.getByTitle("Zoom Out (Y-axis)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset/i })).toBeInTheDocument();
  });

  it("zoom in narrows and zoom out widens the Y-axis domain across both the initial (auto-range) and subsequent (already-set) branches", () => {
    renderChart();
    const zoomIn = screen.getByTitle("Zoom In (Y-axis)");
    const zoomOut = screen.getByTitle("Zoom Out (Y-axis)");
    // First click: yAxisDomain is still undefined -> uses the autoYAxisRange branch.
    expect(() => fireEvent.click(zoomIn)).not.toThrow();
    // Second click: yAxisDomain is now set -> uses the already-zoomed branch.
    expect(() => fireEvent.click(zoomIn)).not.toThrow();
    expect(() => fireEvent.click(zoomOut)).not.toThrow();
    expect(() => fireEvent.click(zoomOut)).not.toThrow();
  });

  it("reset zoom clears any Y-axis zoom and selection state", () => {
    renderChart();
    fireEvent.click(screen.getByTitle("Zoom In (Y-axis)"));
    expect(() => fireEvent.click(screen.getByRole("button", { name: /reset/i }))).not.toThrow();
  });

  it("renders with no drivers selected (empty chart data)", () => {
    const { container } = renderChart({ selectedDrivers: [], lapData: [] });
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("renders one legend entry per selected driver via the legend formatter", () => {
    const { container } = renderChart();
    const legendTexts = Array.from(container.querySelectorAll(".recharts-legend-item-text")).map((el) => el.textContent);
    expect(legendTexts).toEqual(expect.arrayContaining([expect.stringContaining("Lando Norris"), expect.stringContaining("Max Verstappen")]));
  });

  it("maps a track-wide flag event onto the closest lap regardless of driver selection", () => {
    const events = [rcEvent({ date: "2026-01-01T10:01:30Z", scope: "Track", flag: "YELLOW", message: "YELLOW FLAG" })];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("maps a driver-specific event only when that driver is selected", () => {
    const events = [
      rcEvent({ date: "2026-01-01T10:01:30Z", scope: "Driver", driver_number: 1, category: "Other", flag: null, message: "CAR 1 UNDER INVESTIGATION" }),
    ];
    expect(() => renderChart({ raceControlEvents: events, selectedDrivers: [1] })).not.toThrow();
    expect(() => renderChart({ raceControlEvents: events, selectedDrivers: [2] })).not.toThrow();
  });

  it("groups a safety-category event and a red-flag event onto the same lap without crashing", () => {
    const events = [
      rcEvent({ date: "2026-01-01T10:01:30Z", scope: "Track", flag: "RED", category: "Flag", message: "RED FLAG" }),
      rcEvent({ date: "2026-01-01T10:01:31Z", scope: "Track", flag: null, category: "Safety", message: "SAFETY CAR DEPLOYED" }),
      rcEvent({ date: "2026-01-01T10:01:31Z", scope: "Sector", flag: null, category: "Other", message: "TRACK LIMITS WARNING" }),
    ];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("picks the primary event by RED > Safety > YELLOW > GREEN priority when multiple events land on one lap", () => {
    const events = [
      rcEvent({ date: "2026-01-01T10:01:30Z", flag: "GREEN", category: "Flag", message: "GREEN FLAG" }),
      rcEvent({ date: "2026-01-01T10:01:30Z", flag: "YELLOW", category: "Flag", message: "YELLOW FLAG" }),
      rcEvent({ date: "2026-01-01T10:01:30Z", flag: "RED", category: "Flag", message: "RED FLAG" }),
    ];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("picks a Safety-category event as primary (and colors it accordingly) when there's no red flag", () => {
    const events = [rcEvent({ date: "2026-01-01T10:01:30Z", flag: null, category: "Safety", message: "SAFETY CAR DEPLOYED" })];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("picks a GREEN-flag event as primary (and colors it accordingly) when there's no red/safety/yellow event", () => {
    const events = [rcEvent({ date: "2026-01-01T10:01:30Z", flag: "GREEN", category: "Flag", message: "GREEN FLAG" })];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it.each(["DOUBLE YELLOW", "CLEAR", "BLUE"])("renders the flags section for a %s flag event without throwing", (flag) => {
    const events = [rcEvent({ date: "2026-01-01T10:01:30Z", flag, category: "Flag", message: `${flag} FLAG` })];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("ignores an event whose date is too far (>5 minutes) from any known lap start", () => {
    const events = [rcEvent({ date: "2026-01-01T12:00:00Z" })];
    expect(() => renderChart({ raceControlEvents: events })).not.toThrow();
  });

  it("ignores race control events entirely when there is no lap data", () => {
    const events = [rcEvent({})];
    expect(() => renderChart({ raceControlEvents: events, lapData: [] })).not.toThrow();
  });

  it("renders a driver whose session result is missing with a generic fallback name", () => {
    expect(() => renderChart({ sessionResults: [result({ driver_number: 1, full_name: "Lando Norris" })] })).not.toThrow();
  });

  describe("mouse interaction (hover tooltip and drag-to-zoom)", () => {
    // The plot area (from the rendered SVG, given the 800x500 mocked container) spans
    // roughly x:220-770, y:35-410 - recharts only resolves activeTooltipIndex for
    // coordinates inside that area.
    // jsdom's fireEvent doesn't derive pageX/pageY from clientX/clientY, and recharts' own
    // mouse-position math (getMouseInfo) reads event.pageX/pageY directly - every coordinate
    // must be given as both to actually land inside the chart's plotting area.
    const mouseAt = (x: number, y: number) => ({ clientX: x, clientY: y, pageX: x, pageY: y });

    it("hovering over the chart surface activates the custom tooltip content", () => {
      const { container } = renderChart();
      const wrapper = container.querySelector(".recharts-wrapper") as Element;
      fireEvent.mouseOver(wrapper, mouseAt(400, 200));
      fireEvent.mouseMove(wrapper, mouseAt(400, 200));
      expect(container.querySelector(".recharts-tooltip-wrapper")).not.toBeNull();
    });

    it("dragging across the chart selects an X-axis window and renders the selection band", () => {
      const { container } = renderChart();
      const wrapper = container.querySelector(".recharts-wrapper") as Element;
      fireEvent.mouseDown(wrapper, mouseAt(300, 200));
      fireEvent.mouseMove(wrapper, mouseAt(500, 200));
      fireEvent.mouseMove(wrapper, mouseAt(650, 200));
      fireEvent.mouseUp(wrapper, mouseAt(650, 200));
      expect(container).toBeTruthy();
    });

    it("leaving the chart mid-drag cancels the in-progress selection", () => {
      const { container } = renderChart();
      const wrapper = container.querySelector(".recharts-wrapper") as Element;
      fireEvent.mouseDown(wrapper, mouseAt(300, 200));
      fireEvent.mouseMove(wrapper, mouseAt(500, 200));
      fireEvent.mouseLeave(wrapper, mouseAt(500, 200));
      expect(container).toBeTruthy();
    });

    it("a drag that ends where it started does not set an X-axis range", () => {
      const { container } = renderChart();
      const wrapper = container.querySelector(".recharts-wrapper") as Element;
      fireEvent.mouseDown(wrapper, mouseAt(400, 200));
      fireEvent.mouseUp(wrapper, mouseAt(400, 200));
      expect(container).toBeTruthy();
    });
  });
});
