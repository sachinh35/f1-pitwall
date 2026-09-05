import { useEffect, useRef, useState } from "react";
import { clearLiveRoster, rosterEntryFromWire, setLiveRoster } from "../data/driverRoster";
import type { DriverRosterWireEntry } from "../data/driverRoster";
import { connectRaceModeStream } from "../services/sse";
import {
  BattleRadarAlert,
  DriverListInfo,
  DriverTiming,
  ExtrapolatedClockData,
  LapCountData,
  PositionSample,
  RaceControlEntry,
  SessionInfoData,
  TelemetrySample,
  TimingAppDataInfo,
  TimingStatsInfo,
  TopThreeInfo,
  TrackStatus,
  TyreStrategyPredictionWire,
  Weather,
} from "../types/raceMode";
import {
  addDriverEvent,
  DriverEventMarker,
  formatPitStopLabel,
  formatTyreChangeLabel,
  isNewPitStop,
  LapMetricPoint,
  parseTimeToSeconds,
  scanRaceControlEntriesForPenalties,
  sectorIndexForMetric,
  upsertLapMetricPoint,
  DiscreteCompareMetric,
} from "../utils/compareMetrics";
import { usePositionPlayback } from "./usePositionPlayback";
import { useQualifyingResults } from "./useQualifyingResults";
import { useTeamRadioClips } from "./useTeamRadioClips";

function applyRosterWire(wire: Record<string, DriverRosterWireEntry>): void {
  setLiveRoster(
    Object.fromEntries(Object.values(wire).map((entry) => [entry.driver_number, rosterEntryFromWire(entry)]))
  );
}

interface SessionState {
  sessionKey: number | null;
  drivers: Record<string, DriverTiming>;
  driverList: Record<string, DriverListInfo>;
  timingAppData: Record<string, TimingAppDataInfo>;
  timingStats: Record<string, TimingStatsInfo>;
  topThree: Record<string, TopThreeInfo>;
  trackStatus: TrackStatus;
  weather: Weather;
  sessionInfo: SessionInfoData;
  lapCount: LapCountData;
  extrapolatedClock: ExtrapolatedClockData;
  raceControlMessages: Record<string, RaceControlEntry>;
  battleRadar: Record<string, BattleRadarAlert>;
  tyreStrategyPredictions: Record<string, TyreStrategyPredictionWire>;
  qualifyingPart: string | null;
  eliminatedDrivers: number[];
  qualifyingGaps: Record<string, number>;
}

const INITIAL_STATE: SessionState = {
  sessionKey: null,
  drivers: {},
  driverList: {},
  timingAppData: {},
  timingStats: {},
  topThree: {},
  trackStatus: {},
  weather: {},
  sessionInfo: {},
  lapCount: {},
  extrapolatedClock: {},
  raceControlMessages: {},
  battleRadar: {},
  tyreStrategyPredictions: {},
  qualifyingPart: null,
  eliminatedDrivers: [],
  qualifyingGaps: {},
};

export interface LiveSessionRefs {
  /** High-frequency telemetry bypasses React state entirely - CompareWidget reads this
   * directly every animation frame instead. */
  telemetryRef: React.MutableRefObject<Record<string, TelemetrySample>>;
  positionsRef: React.MutableRefObject<Record<string, PositionSample>>;
  trailRef: React.MutableRefObject<Record<string, { x: number; y: number }[]>>;
  /** Per-metric, per-driver lap history for the "discrete" Compare Widget metrics (sector
   * times, lap time) - see CompareWidget.tsx. */
  lapMetricHistoryRef: React.MutableRefObject<Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>>;
  /** Each driver's latest known NumberOfLaps - lets CompareWidget's continuous
   * (speed/throttle/brake) charts tag each buffered telemetry sample with the lap it was
   * captured on, since telemetry itself carries no lap number. */
  currentLapRef: React.MutableRefObject<Record<number, number>>;
  /** Pit stop / tyre change / penalty markers accumulated across the session, per driver -
   * see CompareWidget.tsx's event-marker overlay. */
  driverEventsRef: React.MutableRefObject<Record<number, DriverEventMarker[]>>;
}

export interface LiveSessionState {
  state: SessionState;
  connected: boolean;
  /** Whether any Position.z/CarData.z has actually been received this session - gates the
   * Track Map / Telemetry Compare / Lap Delta widgets. Not assumed from session type: F1
   * sometimes doesn't send these topics at all for a given live connection, so this
   * self-heals whenever that's resolved rather than hardcoding it off for qualifying. */
  hasPositionData: boolean;
  hasTelemetryData: boolean;
  teamRadioClips: ReturnType<typeof useTeamRadioClips>["clips"];
  qualifyingResults: ReturnType<typeof useQualifyingResults>["results"];
  refs: LiveSessionRefs;
}

/**
 * Owns one live/simulated session's full state for a given streamId: connects over SSE,
 * merges every incoming message into a consumable snapshot, and composes the smaller
 * per-concern hooks (position playback, team radio, qualifying results) that also need
 * that stream's data. Shared identically by QualifyingDashboard and RaceDashboard - which
 * widgets get rendered from this state is entirely their concern, not this hook's.
 */
export function useLiveSessionState(streamId: string | undefined): LiveSessionState {
  const [state, setState] = useState<SessionState>(INITIAL_STATE);
  const [connected, setConnected] = useState(false);
  const [hasPositionData, setHasPositionData] = useState(false);
  const [hasTelemetryData, setHasTelemetryData] = useState(false);

  const telemetryRef = useRef<Record<string, TelemetrySample>>({});
  const lapMetricHistoryRef = useRef<Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>>({
    sector1: {},
    sector2: {},
    sector3: {},
    lapTime: {},
  });
  const currentLapRef = useRef<Record<number, number>>({});
  const driverEventsRef = useRef<Record<number, DriverEventMarker[]>>({});
  // "Last known NumberOfPitStops per driver" - see isNewPitStop's own comment for why this
  // must be a genuine increase, not just ">0".
  const lastSeenPitStopsRef = useRef<Record<number, number>>({});
  // "Highest TimingAppDataInfo.Stints index seen per driver" - a stint key not seen before
  // means a tyre change happened. Seeded from the initial snapshot so a driver's starting
  // tyre isn't itself misreported as a "change".
  const highestStintIndexRef = useRef<Record<number, number>>({});
  // Race control message keys already scanned for a penalty - RaceControlMessages resends
  // full state, and message keys are stable, so this prevents re-scanning the same entry.
  const seenRaceControlKeysRef = useRef<Set<string>>(new Set());

  const { positionsRef, trailRef, feedBatch: feedPositionBatch, reset: resetPositionPlayback } = usePositionPlayback();
  const { clips: teamRadioClips, refresh: refreshTeamRadio, reset: resetTeamRadio } = useTeamRadioClips(
    state.sessionKey
  );
  const { results: qualifyingResults, reset: resetQualifyingResults } = useQualifyingResults(
    state.sessionKey,
    state.qualifyingPart
  );

  useEffect(() => {
    if (!streamId) return;

    // Resets every piece of session state/refs when navigating between different live
    // streams (React Router reuses this component across a param-only route change rather
    // than remounting it) - deliberate, not derivable.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(INITIAL_STATE);
    telemetryRef.current = {};
    lapMetricHistoryRef.current = { sector1: {}, sector2: {}, sector3: {}, lapTime: {} };
    currentLapRef.current = {};
    driverEventsRef.current = {};
    lastSeenPitStopsRef.current = {};
    highestStintIndexRef.current = {};
    seenRaceControlKeysRef.current = new Set();
    clearLiveRoster();
    resetPositionPlayback();
    resetTeamRadio();
    resetQualifyingResults();
    setConnected(true);
    setHasPositionData(false);
    setHasTelemetryData(false);

    const scanForPenalties = (entries: Record<string, RaceControlEntry>) =>
      scanRaceControlEntriesForPenalties(entries, seenRaceControlKeysRef.current, driverEventsRef.current);

    const disconnect = connectRaceModeStream(streamId, {
      snapshot: (snapshot) => {
        setState({
          sessionKey: snapshot.session_key,
          drivers: snapshot.drivers,
          driverList: snapshot.driver_list,
          timingAppData: snapshot.timing_app_data,
          timingStats: snapshot.timing_stats,
          topThree: snapshot.top_three,
          trackStatus: snapshot.track_status,
          weather: snapshot.weather,
          sessionInfo: snapshot.session_info,
          lapCount: snapshot.lap_count,
          extrapolatedClock: snapshot.extrapolated_clock,
          raceControlMessages: snapshot.race_control_messages,
          battleRadar: snapshot.battle_radar ?? {},
          tyreStrategyPredictions: snapshot.tyre_strategy_predictions ?? {},
          qualifyingPart: snapshot.qualifying_part,
          eliminatedDrivers: snapshot.eliminated_drivers ?? [],
          qualifyingGaps: snapshot.qualifying_gaps ?? {},
        });
        if (snapshot.driver_roster) applyRosterWire(snapshot.driver_roster);

        // Seed the pit-stop/tyre-stint "last seen" baselines from the snapshot so the first
        // live TimingData/TimingAppData message after connecting doesn't misread "this
        // driver already has N pit stops / stint 0" as a brand-new transition - only a
        // genuine *increase* over this baseline counts (see the TimingData/TimingAppData
        // handlers below). Race control messages, unlike those two, carry their own
        // complete lap/text with each entry, so historical penalties already in the
        // snapshot are backfilled for real rather than merely used to seed a baseline.
        for (const [driverStr, driver] of Object.entries(snapshot.drivers)) {
          if (typeof driver.NumberOfPitStops === "number") {
            lastSeenPitStopsRef.current[Number(driverStr)] = driver.NumberOfPitStops;
          }
        }
        for (const [driverStr, appData] of Object.entries(snapshot.timing_app_data)) {
          if (!appData.Stints) continue;
          const driverNumber = Number(driverStr);
          let highest = highestStintIndexRef.current[driverNumber] ?? -1;
          for (const stintKey of Object.keys(appData.Stints)) {
            const stintIndex = Number(stintKey);
            if (Number.isFinite(stintIndex) && stintIndex > highest) highest = stintIndex;
          }
          highestStintIndexRef.current[driverNumber] = highest;
        }
        scanForPenalties(snapshot.race_control_messages);
      },
      driver_roster: (data) => {
        if (data.driver_roster) applyRosterWire(data.driver_roster);
      },
      TimingData: (data) => {
        if (data.drivers) {
          // Each entry is the full current resolved DriverTiming for that driver (not a
          // partial patch - see diff_to_wire), so Sectors/LastLapTime/SectorsLap/
          // NumberOfLaps are always safe to read directly whenever present.
          for (const [driverStr, driver] of Object.entries(data.drivers)) {
            const driverNumber = Number(driverStr);

            if (typeof driver.NumberOfLaps === "number") {
              currentLapRef.current[driverNumber] = driver.NumberOfLaps;
            }

            if (typeof driver.NumberOfPitStops === "number") {
              if (isNewPitStop(lastSeenPitStopsRef.current[driverNumber], driver.NumberOfPitStops)) {
                const lap = driver.NumberOfLaps ?? currentLapRef.current[driverNumber] ?? 0;
                addDriverEvent(driverEventsRef.current, driverNumber, {
                  lap,
                  kind: "pit",
                  label: formatPitStopLabel(lap),
                });
              }
              lastSeenPitStopsRef.current[driverNumber] = driver.NumberOfPitStops;
            }

            if (driver.Sectors && typeof driver.SectorsLap === "number") {
              (["sector1", "sector2", "sector3"] as const).forEach((metric) => {
                const sectorIndex = sectorIndexForMetric(metric);
                /* v8 ignore next -- sectorIndexForMetric only returns null for "lapTime", never in this literal sector1/2/3 loop; defensive only */
                if (sectorIndex === null) return;
                const seconds = parseTimeToSeconds(driver.Sectors?.[sectorIndex]?.Value);
                if (seconds === null) return;
                upsertLapMetricPoint(
                  lapMetricHistoryRef.current[metric],
                  driverNumber,
                  driver.SectorsLap!,
                  seconds
                );
              });
            }

            if (driver.LastLapTime && typeof driver.NumberOfLaps === "number") {
              const seconds = parseTimeToSeconds(driver.LastLapTime.Value);
              if (seconds !== null) {
                upsertLapMetricPoint(lapMetricHistoryRef.current.lapTime, driverNumber, driver.NumberOfLaps, seconds);
              }
            }
          }

          setState((prev) => ({ ...prev, drivers: { ...prev.drivers, ...data.drivers } }));
        }
        if (data.qualifying_gaps) {
          // Full table every time (see sse.ts) - a straight replace, not a merge, so a
          // driver who lost their only valid lap (deleted) correctly drops out instead of
          // keeping a stale entry.
          setState((prev) => ({ ...prev, qualifyingGaps: data.qualifying_gaps! }));
        }
        if (data.battle_radar) {
          const updates = data.battle_radar;
          setState((prev) => {
            const battleRadar = { ...prev.battleRadar };
            for (const [driverStr, alert] of Object.entries(updates)) {
              if (alert) battleRadar[driverStr] = alert;
              else delete battleRadar[driverStr];
            }
            return { ...prev, battleRadar };
          });
        }
      },
      DriverList: (data) => {
        if (data.driver_list) {
          setState((prev) => ({ ...prev, driverList: { ...prev.driverList, ...data.driver_list } }));
        }
      },
      TimingAppData: (data) => {
        if (data.timing_app_data) {
          // A stint key not seen before for this driver means a tyre change happened - see
          // highestStintIndexRef's own comment. Tyre-change messages carry no lap number of
          // their own (unlike SectorsLap for sectors), so the best-known current lap
          // (currentLapRef, kept up to date by the TimingData handler above) is used
          // instead, same convention SectorsLap already uses elsewhere in this hook.
          for (const [driverStr, appData] of Object.entries(data.timing_app_data)) {
            if (!appData.Stints) continue;
            const driverNumber = Number(driverStr);
            const highestSeen = highestStintIndexRef.current[driverNumber] ?? -1;
            let newHighest = highestSeen;

            for (const [stintKey, stint] of Object.entries(appData.Stints)) {
              const stintIndex = Number(stintKey);
              if (!Number.isFinite(stintIndex)) continue;
              if (stintIndex > highestSeen) {
                const lap = currentLapRef.current[driverNumber] ?? 0;
                const compound = (stint.Compound ?? "unknown").toLowerCase();
                addDriverEvent(driverEventsRef.current, driverNumber, {
                  lap,
                  kind: "tyre",
                  label: formatTyreChangeLabel(stint.Compound ?? "unknown", lap),
                  compound,
                });
              }
              if (stintIndex > newHighest) newHighest = stintIndex;
            }

            highestStintIndexRef.current[driverNumber] = newHighest;
          }

          setState((prev) => ({ ...prev, timingAppData: { ...prev.timingAppData, ...data.timing_app_data } }));
        }
      },
      TimingStats: (data) => {
        if (data.timing_stats) {
          setState((prev) => ({ ...prev, timingStats: { ...prev.timingStats, ...data.timing_stats } }));
        }
      },
      TopThree: (data) => {
        if (data.top_three) {
          setState((prev) => ({ ...prev, topThree: { ...prev.topThree, ...data.top_three } }));
        }
      },
      TrackStatus: (data) => {
        if (data.track_status) setState((prev) => ({ ...prev, trackStatus: data.track_status! }));
      },
      WeatherData: (data) => {
        if (data.weather) setState((prev) => ({ ...prev, weather: data.weather! }));
      },
      SessionInfo: (data) => {
        setState((prev) => ({
          ...prev,
          sessionInfo: data.session_info ?? prev.sessionInfo,
          sessionKey: data.session_info?.Key ?? prev.sessionKey,
          // qualifying_part can default to "Q1" right here (F1 never announces Q1
          // explicitly) - see sse.ts/SessionState._apply_session_info.
          qualifyingPart: data.qualifying_part !== undefined ? data.qualifying_part ?? null : prev.qualifyingPart,
          eliminatedDrivers: data.eliminated_drivers ?? prev.eliminatedDrivers,
        }));
      },
      SessionData: (data) => {
        setState((prev) => ({
          ...prev,
          qualifyingPart: data.qualifying_part !== undefined ? data.qualifying_part ?? null : prev.qualifyingPart,
          eliminatedDrivers: data.eliminated_drivers ?? prev.eliminatedDrivers,
        }));
      },
      LapCount: (data) => {
        if (data.lap_count) setState((prev) => ({ ...prev, lapCount: data.lap_count! }));
      },
      ExtrapolatedClock: (data) => {
        if (data.extrapolated_clock) setState((prev) => ({ ...prev, extrapolatedClock: data.extrapolated_clock! }));
      },
      RaceControlMessages: (data) => {
        if (data.race_control_messages) {
          scanForPenalties(data.race_control_messages);
          setState((prev) => ({
            ...prev,
            raceControlMessages: { ...prev.raceControlMessages, ...data.race_control_messages },
          }));
        }
      },
      "CarData.z": (data) => {
        if (data.telemetry) {
          telemetryRef.current = { ...telemetryRef.current, ...data.telemetry };
          setHasTelemetryData(true);
        }
      },
      "Position.z": (data) => {
        if (data.positions) {
          feedPositionBatch(data.positions);
          setHasPositionData(true);
        }
      },
      RADIO_CLIP_READY: () => refreshTeamRadio(),
      RADIO_TRANSCRIPT_READY: () => refreshTeamRadio(),
      RADIO_ANALYSIS_READY: () => refreshTeamRadio(),
      TYRE_STRATEGY_PREDICTION: (data) => {
        setState((prev) => ({
          ...prev,
          tyreStrategyPredictions: { ...prev.tyreStrategyPredictions, [String(data.driver_number)]: data.prediction },
        }));
      },
    });

    return () => {
      disconnect();
      setConnected(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resetPositionPlayback/resetTeamRadio/
    // resetQualifyingResults/feedPositionBatch/refreshTeamRadio are all useCallback-stable (see
    // usePositionPlayback/useTeamRadioClips/useQualifyingResults), so they never actually change;
    // listing them would only make this diff noisier for no behavioral difference.
  }, [streamId]);

  return {
    state,
    connected,
    hasPositionData,
    hasTelemetryData,
    teamRadioClips,
    qualifyingResults,
    refs: { telemetryRef, positionsRef, trailRef, lapMetricHistoryRef, currentLapRef, driverEventsRef },
  };
}
