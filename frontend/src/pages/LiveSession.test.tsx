import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import LiveSession from "./LiveSession";
import { useLiveSessionState, LiveSessionState } from "../hooks/useLiveSessionState";

vi.mock("../hooks/useLiveSessionState", () => ({
  useLiveSessionState: vi.fn(),
}));
vi.mock("../services/api", () => ({
  getLapComparison: vi.fn().mockResolvedValue(null),
}));

const mockedUseLiveSessionState = vi.mocked(useLiveSessionState);

function buildSession(sessionType: string | undefined): LiveSessionState {
  return {
    state: {
      sessionKey: 9850,
      drivers: {},
      driverList: {},
      timingAppData: {},
      timingStats: {},
      topThree: {},
      trackStatus: {},
      sessionStatus: {},
      weather: {},
      sessionInfo: { Type: sessionType },
      lapCount: {},
      extrapolatedClock: {},
      raceControlMessages: {},
      battleRadar: {},
      tyreStrategyPredictions: {},
      qualifyingPart: sessionType === "Qualifying" ? "Q1" : null,
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
  };
}

function renderAtStream(streamId: string) {
  return render(
    <MemoryRouter initialEntries={[`/live-stream/${streamId}`]}>
      <Routes>
        <Route path="/live-stream/:streamId" element={<LiveSession />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("LiveSession", () => {
  it("renders QualifyingDashboard for a Qualifying session", () => {
    mockedUseLiveSessionState.mockReturnValue(buildSession("Qualifying"));
    renderAtStream("stream-1");
    expect(screen.getByText("Qualifying Mode")).toBeInTheDocument();
  });

  it("renders RaceDashboard for a Race session", () => {
    mockedUseLiveSessionState.mockReturnValue(buildSession("Race"));
    renderAtStream("stream-1");
    expect(screen.getByText("Race Mode")).toBeInTheDocument();
  });

  it("defaults to RaceDashboard before the session type is known", () => {
    mockedUseLiveSessionState.mockReturnValue(buildSession(undefined));
    renderAtStream("stream-1");
    expect(screen.getByText("Race Mode")).toBeInTheDocument();
  });

  it("passes the streamId from the route param through to the hook", () => {
    mockedUseLiveSessionState.mockReturnValue(buildSession("Race"));
    renderAtStream("stream-42");
    expect(mockedUseLiveSessionState).toHaveBeenCalledWith("stream-42");
  });
});
