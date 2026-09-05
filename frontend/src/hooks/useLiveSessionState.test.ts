import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLiveSessionState } from "./useLiveSessionState";
import { connectRaceModeStream, RaceModeHandlers } from "../services/sse";
import { getQualifyingResults, getTeamRadioForSession } from "../services/api";
import { RaceModeSnapshot } from "../types/raceMode";

vi.mock("../services/sse", () => ({
  connectRaceModeStream: vi.fn(),
}));
vi.mock("../services/api", () => ({
  getTeamRadioForSession: vi.fn(),
  getQualifyingResults: vi.fn(),
}));

const mockedConnect = vi.mocked(connectRaceModeStream);
const mockedGetTeamRadioForSession = vi.mocked(getTeamRadioForSession);
const mockedGetQualifyingResults = vi.mocked(getQualifyingResults);

let capturedHandlers: RaceModeHandlers;
const disconnect = vi.fn();

function emptySnapshot(overrides: Partial<RaceModeSnapshot> = {}): RaceModeSnapshot {
  return {
    session_key: null,
    drivers: {},
    driver_list: {},
    timing_app_data: {},
    timing_stats: {},
    top_three: {},
    track_status: {},
    weather: {},
    session_info: {},
    session_data: {},
    session_status: {},
    lap_count: {},
    extrapolated_clock: {},
    race_control_messages: {},
    driver_roster: {},
    battle_radar: {},
    tyre_strategy_predictions: {},
    qualifying_part: null,
    eliminated_drivers: [],
    qualifying_gaps: {},
    ...overrides,
  };
}

beforeEach(() => {
  mockedGetTeamRadioForSession.mockReset().mockResolvedValue([]);
  mockedGetQualifyingResults.mockReset().mockResolvedValue({});
  disconnect.mockReset();
  mockedConnect.mockReset().mockImplementation((_streamId, handlers) => {
    capturedHandlers = handlers;
    return disconnect;
  });
});

describe("useLiveSessionState", () => {
  it("does not connect when streamId is undefined", () => {
    renderHook(() => useLiveSessionState(undefined));
    expect(mockedConnect).not.toHaveBeenCalled();
  });

  it("connects and reports connected=true once a streamId is given", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    expect(mockedConnect).toHaveBeenCalledWith("stream-1", expect.any(Object));
    expect(result.current.connected).toBe(true);
  });

  it("disconnects and reports connected=false on unmount", () => {
    const { result, unmount } = renderHook(() => useLiveSessionState("stream-1"));
    expect(result.current.connected).toBe(true);
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });

  it("reconnects with a fresh state when streamId changes", () => {
    const { rerender } = renderHook(({ id }) => useLiveSessionState(id), { initialProps: { id: "stream-1" } });
    act(() => capturedHandlers.snapshot!(emptySnapshot({ session_key: 111 })));

    rerender({ id: "stream-2" });

    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(mockedConnect).toHaveBeenLastCalledWith("stream-2", expect.any(Object));
  });

  it("applies a snapshot's fields into state", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.snapshot!(
        emptySnapshot({
          session_key: 9850,
          drivers: { "44": { Position: "1" } },
          qualifying_part: "Q1",
          eliminated_drivers: [22],
        })
      );
    });

    expect(result.current.state.sessionKey).toBe(9850);
    expect(result.current.state.drivers["44"].Position).toBe("1");
    expect(result.current.state.qualifyingPart).toBe("Q1");
    expect(result.current.state.eliminatedDrivers).toEqual([22]);
  });

  it("backfills penalty events from the snapshot's race control messages", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.snapshot!(
        emptySnapshot({
          race_control_messages: {
            "1": { Message: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55", Lap: 10 } as never,
          },
        })
      );
    });

    expect(result.current.refs.driverEventsRef.current[55]).toEqual([
      { lap: 10, kind: "penalty", label: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55" },
    ]);
  });

  it("does not misfire a pit-stop event for a driver's very first TimingData message", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingData!({ drivers: { "44": { NumberOfPitStops: 1, NumberOfLaps: 5 } } as never });
    });

    expect(result.current.refs.driverEventsRef.current[44]).toBeUndefined();
  });

  it("fires a pit-stop event only on a genuine increase over the snapshot baseline", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => {
      capturedHandlers.snapshot!(emptySnapshot({ drivers: { "44": { NumberOfPitStops: 1 } as never } }));
    });

    act(() => {
      capturedHandlers.TimingData!({ drivers: { "44": { NumberOfPitStops: 1, NumberOfLaps: 5 } as never } });
    });
    expect(result.current.refs.driverEventsRef.current[44]).toBeUndefined();

    act(() => {
      capturedHandlers.TimingData!({ drivers: { "44": { NumberOfPitStops: 2, NumberOfLaps: 6 } as never } });
    });
    expect(result.current.refs.driverEventsRef.current[44]).toEqual([
      { lap: 6, kind: "pit", label: "Pit stop (lap 6)" },
    ]);
  });

  it("fires a tyre-change event for a stint index not seen before", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingAppData!({
        timing_app_data: { "44": { Stints: { "0": { Compound: "Soft" } } } as never },
      });
    });

    expect(result.current.refs.driverEventsRef.current[44]).toHaveLength(1);
    expect(result.current.refs.driverEventsRef.current[44][0].kind).toBe("tyre");
  });

  it("sets hasTelemetryData once CarData.z arrives", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    expect(result.current.hasTelemetryData).toBe(false);

    act(() => {
      capturedHandlers["CarData.z"]!({ telemetry: { "44": { speed: 300 } as never } });
    });

    expect(result.current.hasTelemetryData).toBe(true);
    expect(result.current.refs.telemetryRef.current["44"]).toEqual({ speed: 300 });
  });

  it("sets hasPositionData and feeds the position playback engine once Position.z arrives", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    expect(result.current.hasPositionData).toBe(false);

    act(() => {
      capturedHandlers["Position.z"]!({ positions: { "44": [{ x: 1, y: 2, z: 0, status: "OnTrack" }] } });
    });

    expect(result.current.hasPositionData).toBe(true);
    expect(result.current.refs.trailRef.current["44"]).toEqual([{ x: 1, y: 2 }]);
  });

  it("refetches team radio when a RADIO_CLIP_READY event arrives", async () => {
    renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ session_key: 9850 })));
    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(1));

    act(() => capturedHandlers.RADIO_CLIP_READY!({ row_id: 1 }));

    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(2));
  });

  it("refetches qualifying results once qualifyingPart advances", async () => {
    renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ session_key: 9850, qualifying_part: "Q1" })));
    await waitFor(() => expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(1));

    act(() => capturedHandlers.SessionData!({ qualifying_part: "Q2" }));

    await waitFor(() => expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(2));
  });

  it("merges DriverList/TimingStats/TopThree updates", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => capturedHandlers.DriverList!({ driver_list: { "44": { Tla: "HAM" } as never } }));
    act(() => capturedHandlers.TimingStats!({ timing_stats: { "44": { BestSpeeds: {} } as never } }));
    act(() => capturedHandlers.TopThree!({ top_three: { "1": { Tla: "HAM" } as never } }));

    expect(result.current.state.driverList["44"]).toEqual({ Tla: "HAM" });
    expect(result.current.state.timingStats["44"]).toEqual({ BestSpeeds: {} });
    expect(result.current.state.topThree["1"]).toEqual({ Tla: "HAM" });
  });

  it("replaces TrackStatus/WeatherData/LapCount/ExtrapolatedClock wholesale", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => capturedHandlers.TrackStatus!({ track_status: { Status: "2" } as never }));
    act(() => capturedHandlers.WeatherData!({ weather: { AirTemp: "25.0" } as never }));
    act(() => capturedHandlers.LapCount!({ lap_count: { CurrentLap: 3, TotalLaps: 58 } }));
    act(() => capturedHandlers.ExtrapolatedClock!({ extrapolated_clock: { Remaining: "00:15:00" } as never }));

    expect(result.current.state.trackStatus).toEqual({ Status: "2" });
    expect(result.current.state.weather).toEqual({ AirTemp: "25.0" });
    expect(result.current.state.lapCount).toEqual({ CurrentLap: 3, TotalLaps: 58 });
    expect(result.current.state.extrapolatedClock).toEqual({ Remaining: "00:15:00" });
  });

  it("SessionInfo updates sessionInfo/sessionKey/qualifyingPart/eliminatedDrivers", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() =>
      capturedHandlers.SessionInfo!({
        session_info: { Key: 9850, Type: "Qualifying" },
        qualifying_part: "Q1",
        eliminated_drivers: [],
      })
    );

    expect(result.current.state.sessionInfo).toEqual({ Key: 9850, Type: "Qualifying" });
    expect(result.current.state.sessionKey).toBe(9850);
    expect(result.current.state.qualifyingPart).toBe("Q1");
  });

  it("SessionInfo leaves qualifyingPart untouched when the field is absent from the message", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ qualifying_part: "Q2" })));

    act(() => capturedHandlers.SessionInfo!({ session_info: { Type: "Qualifying" } }));

    expect(result.current.state.qualifyingPart).toBe("Q2");
  });

  it("merges live RaceControlMessages and scans them for penalties", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() =>
      capturedHandlers.RaceControlMessages!({
        race_control_messages: {
          "1": { Message: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55", Lap: 3 } as never,
        },
      })
    );

    expect(result.current.state.raceControlMessages["1"]).toBeDefined();
    expect(result.current.refs.driverEventsRef.current[55]).toHaveLength(1);
  });

  it("upserts sector and lap-time metric history from TimingData", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingData!({
        drivers: {
          "44": {
            NumberOfLaps: 2,
            SectorsLap: 1,
            Sectors: { "0": { Value: "28.500" } },
            LastLapTime: { Value: "1:27.150" },
          } as never,
        },
      });
    });

    expect(result.current.refs.lapMetricHistoryRef.current.sector1[44]).toEqual([{ lap: 1, value: 28.5 }]);
    expect(result.current.refs.lapMetricHistoryRef.current.lapTime[44]).toEqual([{ lap: 2, value: 87.15 }]);
  });

  it("replaces qualifying gaps wholesale and merges/clears battle radar alerts", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingData!({ qualifying_gaps: { "44": 0.5 } });
    });
    expect(result.current.state.qualifyingGaps).toEqual({ "44": 0.5 });

    act(() => {
      capturedHandlers.TimingData!({ battle_radar: { "44": { closing: true } as never } });
    });
    expect(result.current.state.battleRadar["44"]).toEqual({ closing: true });

    act(() => {
      capturedHandlers.TimingData!({ battle_radar: { "44": null } });
    });
    expect(result.current.state.battleRadar["44"]).toBeUndefined();
  });

  it("does not add a duplicate tyre-change event for a stint index already seen", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => {
      capturedHandlers.TimingAppData!({ timing_app_data: { "44": { Stints: { "0": { Compound: "Soft" } } } as never } });
    });
    expect(result.current.refs.driverEventsRef.current[44]).toHaveLength(1);

    act(() => {
      capturedHandlers.TimingAppData!({ timing_app_data: { "44": { Stints: { "0": { Compound: "Soft" } } } as never } });
    });

    expect(result.current.refs.driverEventsRef.current[44]).toHaveLength(1);
  });

  it("stores a driver's predicted tyre strategy from TYRE_STRATEGY_PREDICTION", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TYRE_STRATEGY_PREDICTION!({ driver_number: 44, prediction: { strategy: "1-stop" } as never });
    });

    expect(result.current.state.tyreStrategyPredictions["44"]).toEqual({ strategy: "1-stop" });
  });

  it("defaults battleRadar/tyreStrategyPredictions/eliminatedDrivers/qualifyingGaps when a snapshot omits them", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.snapshot!(
        emptySnapshot({
          battle_radar: undefined as never,
          tyre_strategy_predictions: undefined as never,
          eliminated_drivers: undefined as never,
          qualifying_gaps: undefined as never,
          driver_roster: undefined as never,
        })
      );
    });

    expect(result.current.state.battleRadar).toEqual({});
    expect(result.current.state.tyreStrategyPredictions).toEqual({});
    expect(result.current.state.eliminatedDrivers).toEqual([]);
    expect(result.current.state.qualifyingGaps).toEqual({});
  });

  it("seeds the highest-seen stint index per driver from a snapshot with real stints", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.snapshot!(
        emptySnapshot({
          timing_app_data: {
            // Descending/repeated indices exercise the "not a new highest" branch too, not
            // just the monotonically-increasing case.
            "44": {
              Stints: { "0": { Compound: "Soft" }, "1": { Compound: "Medium" }, notanumber: { Compound: "Hard" } },
            } as never,
            "1": {} as never, // no Stints at all - must be skipped, not throw
          },
        })
      );
    });

    // A stint index already seeded by the snapshot (1) must not re-fire as a "new" tyre
    // change when the exact same data arrives again live.
    act(() => {
      capturedHandlers.TimingAppData!({
        timing_app_data: { "44": { Stints: { "1": { Compound: "Medium" } } } as never },
      });
    });

    expect(result.current.refs.driverEventsRef.current[44]).toBeUndefined();
  });

  it("applies the top-level driver_roster event", () => {
    renderHook(() => useLiveSessionState("stream-1"));

    expect(() =>
      act(() =>
        capturedHandlers.driver_roster!({
          driver_roster: { "44": { driver_number: 44, tla: "HAM" } as never },
        })
      )
    ).not.toThrow();
  });

  it("ignores a driver_roster event with no payload", () => {
    renderHook(() => useLiveSessionState("stream-1"));
    expect(() => act(() => capturedHandlers.driver_roster!({}))).not.toThrow();
  });

  it("fires RADIO_TRANSCRIPT_READY/RADIO_ANALYSIS_READY refreshes too", async () => {
    renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ session_key: 9850 })));
    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(1));

    act(() => capturedHandlers.RADIO_TRANSCRIPT_READY!({ row_id: 1 }));
    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(2));

    act(() => capturedHandlers.RADIO_ANALYSIS_READY!({ row_id: 1 }));
    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(3));
  });

  it("falls back to lap 0 for a pit stop when neither NumberOfLaps nor a known current lap exists", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ drivers: { "44": { NumberOfPitStops: 1 } as never } })));

    act(() => capturedHandlers.TimingData!({ drivers: { "44": { NumberOfPitStops: 2 } as never } }));

    expect(result.current.refs.driverEventsRef.current[44]).toEqual([
      { lap: 0, kind: "pit", label: "Pit stop (lap 0)" },
    ]);
  });

  it("does not upsert a lap time when LastLapTime's value is unparseable", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingData!({
        drivers: { "44": { NumberOfLaps: 2, LastLapTime: { Value: "not-a-time" } } as never },
      });
    });

    expect(result.current.refs.lapMetricHistoryRef.current.lapTime[44]).toBeUndefined();
  });

  it("skips a live TimingAppData driver entry with no Stints, and a non-finite stint key", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    expect(() =>
      act(() => {
        capturedHandlers.TimingAppData!({
          timing_app_data: {
            "1": {} as never,
            "44": { Stints: { notanumber: { Compound: "Soft" } } } as never,
          },
        });
      })
    ).not.toThrow();

    expect(result.current.refs.driverEventsRef.current[1]).toBeUndefined();
    expect(result.current.refs.driverEventsRef.current[44]).toBeUndefined();
  });

  it("labels a tyre change as unknown compound when the stint carries none", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));

    act(() => {
      capturedHandlers.TimingAppData!({ timing_app_data: { "44": { Stints: { "0": {} } } as never } });
    });

    expect(result.current.refs.driverEventsRef.current[44][0].compound).toBe("unknown");
  });

  it("SessionInfo falls back to the previous sessionInfo/sessionKey when the message omits them", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() =>
      capturedHandlers.SessionInfo!({ session_info: { Key: 9850, Type: "Race" }, qualifying_part: null })
    );

    act(() => capturedHandlers.SessionInfo!({ qualifying_part: null }));

    expect(result.current.state.sessionInfo).toEqual({ Key: 9850, Type: "Race" });
    expect(result.current.state.sessionKey).toBe(9850);
  });

  it("SessionData accepts an explicit null qualifyingPart (distinct from omitting the field)", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ qualifying_part: "Q1" })));

    act(() => capturedHandlers.SessionData!({ qualifying_part: null }));

    expect(result.current.state.qualifyingPart).toBeNull();
  });

  it("SessionData leaves qualifyingPart/eliminatedDrivers untouched when the message omits them", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    act(() => capturedHandlers.snapshot!(emptySnapshot({ qualifying_part: "Q1", eliminated_drivers: [22] })));

    act(() => capturedHandlers.SessionData!({}));

    expect(result.current.state.qualifyingPart).toBe("Q1");
    expect(result.current.state.eliminatedDrivers).toEqual([22]);
  });

  it("ignores handler calls whose payload field is absent, leaving state unchanged", () => {
    const { result } = renderHook(() => useLiveSessionState("stream-1"));
    const before = result.current.state;

    act(() => {
      capturedHandlers.TimingData!({});
      capturedHandlers.DriverList!({});
      capturedHandlers.TimingAppData!({});
      capturedHandlers.TimingStats!({});
      capturedHandlers.TopThree!({});
      capturedHandlers.TrackStatus!({});
      capturedHandlers.WeatherData!({});
      capturedHandlers.LapCount!({});
      capturedHandlers.ExtrapolatedClock!({});
      capturedHandlers.RaceControlMessages!({});
      capturedHandlers["CarData.z"]!({});
      capturedHandlers["Position.z"]!({});
    });

    expect(result.current.state).toBe(before);
    expect(result.current.hasTelemetryData).toBe(false);
    expect(result.current.hasPositionData).toBe(false);
  });
});
