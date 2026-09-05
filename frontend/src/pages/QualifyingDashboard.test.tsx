import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import QualifyingDashboard from "./QualifyingDashboard";
import { LiveSessionState } from "../hooks/useLiveSessionState";

vi.mock("../services/api", () => ({
  getLapComparison: vi.fn().mockResolvedValue(null),
}));

function buildSession(overrides: Partial<LiveSessionState> = {}): LiveSessionState {
  return {
    state: {
      sessionKey: 9850,
      drivers: {},
      driverList: {},
      timingAppData: {},
      timingStats: {},
      topThree: {},
      trackStatus: {},
      weather: {},
      sessionInfo: { Type: "Qualifying", Meeting: { Name: "Italian Grand Prix" } },
      lapCount: {},
      extrapolatedClock: {},
      raceControlMessages: {},
      battleRadar: {},
      tyreStrategyPredictions: {},
      qualifyingPart: "Q1",
      eliminatedDrivers: [],
      qualifyingGaps: {},
    },
    connected: true,
    hasPositionData: false,
    hasTelemetryData: false,
    teamRadioClips: [],
    qualifyingResults: {},
    refs: {
      telemetryRef: { current: {} },
      positionsRef: { current: {} },
      trailRef: { current: {} },
      lapMetricHistoryRef: { current: { sector1: {}, sector2: {}, sector3: {}, lapTime: {} } },
      currentLapRef: { current: {} },
      driverEventsRef: { current: {} },
    },
    ...overrides,
  };
}

function renderDashboard(session: LiveSessionState) {
  return render(
    <MemoryRouter>
      <QualifyingDashboard session={session} />
    </MemoryRouter>
  );
}

describe("QualifyingDashboard", () => {
  it("renders the Qualifying Mode title and current segment pill", () => {
    renderDashboard(buildSession());
    expect(screen.getByText("Qualifying Mode")).toBeInTheDocument();
    expect(screen.getByText("QUALIFYING – Q1")).toBeInTheDocument();
  });

  it("shows the meeting name when known", () => {
    renderDashboard(buildSession());
    expect(screen.getByText("Italian Grand Prix")).toBeInTheDocument();
  });

  it("shows a bare QUALIFYING pill before any segment is known", () => {
    renderDashboard(
      buildSession({
        state: { ...buildSession().state, qualifyingPart: null },
      })
    );
    expect(screen.getByText("QUALIFYING")).toBeInTheDocument();
  });

  it("shows the LIVE pill only while connected", () => {
    const { rerender } = renderDashboard(buildSession({ connected: true }));
    expect(screen.getByText("LIVE")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <QualifyingDashboard session={buildSession({ connected: false })} />
      </MemoryRouter>
    );
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("hides the Track Map panel until position data has arrived", () => {
    renderDashboard(buildSession({ hasPositionData: false }));
    expect(screen.queryByText("Track Map")).not.toBeInTheDocument();
  });

  it("shows the Track Map panel once position data has arrived", () => {
    renderDashboard(buildSession({ hasPositionData: true }));
    expect(screen.getByText("Track Map")).toBeInTheDocument();
  });

  it("hides the Lap Delta panel until both telemetry and position data have arrived", () => {
    renderDashboard(buildSession({ hasTelemetryData: true, hasPositionData: false }));
    expect(screen.queryByText("Lap Delta & Corner Analysis")).not.toBeInTheDocument();
  });

  it("shows the Lap Delta panel once both telemetry and position data have arrived", () => {
    renderDashboard(buildSession({ hasTelemetryData: true, hasPositionData: true }));
    expect(screen.getByText("Lap Delta & Corner Analysis")).toBeInTheDocument();
  });

  it("hides the Qualifying Results panel when no segment has finished yet", () => {
    renderDashboard(buildSession({ qualifyingResults: {} }));
    expect(screen.queryByText("Qualifying Results")).not.toBeInTheDocument();
  });

  it("shows the Qualifying Results panel once a segment has finished", () => {
    renderDashboard(
      buildSession({
        qualifyingResults: {
          Q1: [{ driver_number: 1, position: 1, best_lap_seconds: 80, gap_to_leader_seconds: 0, eliminated: false }],
        },
      })
    );
    expect(screen.getByText("Qualifying Results")).toBeInTheDocument();
  });

  it("always renders the Timing Tower and Race Control panels", () => {
    renderDashboard(buildSession());
    expect(screen.getByText("Timing Tower")).toBeInTheDocument();
    expect(screen.getByText("Race Control")).toBeInTheDocument();
  });

  it("can add, reconfigure, and remove a Telemetry Compare widget", () => {
    renderDashboard(buildSession());
    fireEvent.click(screen.getByRole("button", { name: "+ Add Compare" }));

    const metricSelects = screen.getAllByLabelText("Comparison metric");
    fireEvent.change(metricSelects[metricSelects.length - 1], { target: { value: "sector1" } });

    const removeButtons = screen.getAllByLabelText("Remove this comparison widget");
    fireEvent.click(removeButtons[removeButtons.length - 1]);

    expect(screen.getAllByLabelText("Comparison metric")).toHaveLength(metricSelects.length - 1);
  });
});
