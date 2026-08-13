import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import CompareWidget from "../components/racemode/CompareWidget";
import LapDeltaChart from "../components/racemode/LapDeltaChart";
import RaceControlFeed from "../components/racemode/RaceControlFeed";
import SessionClock from "../components/racemode/SessionClock";
import TeamRadioPanel from "../components/racemode/TeamRadioPanel";
import TimingTower from "../components/racemode/TimingTower";
import TrackMap from "../components/racemode/TrackMap";
import TrackStatusBanner from "../components/racemode/TrackStatusBanner";
import { clearLiveRoster, rosterEntryFromWire, setLiveRoster } from "../data/driverRoster";
import type { DriverRosterWireEntry } from "../data/driverRoster";
import { getTeamRadioForSession } from "../services/api";
import { connectRaceModeStream } from "../services/sse";
import "../styles/raceMode.css";
import {
  BattleRadarAlert,
  DriverListInfo,
  DriverTiming,
  ExtrapolatedClockData,
  LapCountData,
  PositionSample,
  RaceControlEntry,
  SessionInfoData,
  TeamRadioClip,
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
  CompareMetric,
  DiscreteCompareMetric,
  DriverEventMarker,
  extractPenaltyDriverNumber,
  formatPenaltyLabel,
  formatPitStopLabel,
  formatTyreChangeLabel,
  isPenaltyMessage,
  LapMetricPoint,
  parseTimeToSeconds,
  sectorIndexForMetric,
  upsertLapMetricPoint,
} from "../utils/compareMetrics";

function applyRosterWire(wire: Record<string, DriverRosterWireEntry>): void {
  setLiveRoster(
    Object.fromEntries(Object.values(wire).map((entry) => [entry.driver_number, rosterEntryFromWire(entry)]))
  );
}

interface SlowState {
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

const INITIAL_STATE: SlowState = {
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

interface CompareWidgetConfig {
  id: string;
  metric: CompareMetric;
}

// Default view (first load) preserves today's fixed 3-band layout: Speed/Throttle/Brake,
// in that order, so nothing regresses for an existing user.
const DEFAULT_COMPARE_WIDGETS: CompareWidgetConfig[] = [
  { id: "compare-0", metric: "speed" },
  { id: "compare-1", metric: "throttle" },
  { id: "compare-2", metric: "brake" },
];

const RaceMode: React.FC = () => {
  const { streamId } = useParams<{ streamId: string }>();
  const [state, setState] = useState<SlowState>(INITIAL_STATE);
  const [selectedDrivers, setSelectedDrivers] = useState<number[]>([]);
  // Regular React state (not a ref) - changes only when the user adds/removes/reconfigures a
  // widget, a rare, human-paced event, unlike the histories/telemetry these widgets read.
  const [compareWidgets, setCompareWidgets] = useState<CompareWidgetConfig[]>(DEFAULT_COMPARE_WIDGETS);
  // Monotonic counter backing each new widget's React key - a ref (not state) since it's an
  // implementation detail that should never itself trigger a re-render.
  const nextCompareWidgetId = useRef(DEFAULT_COMPARE_WIDGETS.length);
  const [radioRefreshSignal, setRadioRefreshSignal] = useState(0);
  const [teamRadioClips, setTeamRadioClips] = useState<TeamRadioClip[]>([]);
  const [connected, setConnected] = useState(false);
  // Pins the right-column panel rail's height to the Timing Tower panel's actual rendered
  // height (see the .rm-right-rail div below), so Team Radio scrolls internally instead of
  // growing to fit every message. Plain CSS (grid stretch + flex:1/min-height:0) can't do
  // this: a grid track's "auto" height is computed from the *max-content* size of every
  // item spanning it, including a flex child's full, uncollapsed message-list height -
  // min-height:0 only lets a flex item shrink once its container already has a definite
  // size, so it can't break this circularity on its own. Measuring the tower directly and
  // applying that as an explicit height sidesteps the auto-sizing pass entirely.
  const timingTowerPanelRef = useRef<HTMLDivElement | null>(null);
  const [timingTowerHeight, setTimingTowerHeight] = useState<number | null>(null);
  useEffect(() => {
    const el = timingTowerPanelRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      setTimingTowerHeight(entries[0].contentRect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  // Whether any Position.z/CarData.z has actually been received this session - gates the
  // Track Map / Telemetry Compare / Lap Delta widgets. Not assumed from session type: F1
  // sometimes doesn't send these topics at all for a given live connection (confirmed
  // against a real session, quali and race captures both had them historically), so this
  // self-heals whenever that's resolved rather than hardcoding it off for qualifying.
  const [hasPositionData, setHasPositionData] = useState(false);
  const [hasTelemetryData, setHasTelemetryData] = useState(false);

  // High-frequency telemetry/position bypass React state entirely - Canvas
  // components read these refs directly every animation frame instead.
  const telemetryRef = useRef<Record<string, TelemetrySample>>({});
  const positionsRef = useRef<Record<string, PositionSample>>({});
  // Per-driver position history - draws the track outline itself in TrackMap,
  // since F1's feed never sends circuit geometry (see TrackMap.tsx).
  const trailRef = useRef<Record<string, { x: number; y: number }[]>>({});
  const MAX_TRAIL_POINTS_PER_DRIVER = 2000;
  // Per-metric, per-driver lap history for the "discrete" Compare Widget metrics (sector
  // times, lap time) - these only produce a new definitive value once per lap (or per
  // sector) per driver, from TimingData rather than CarData.z, so unlike telemetryRef they
  // can't just be read live off the current sample - see the TimingData handler below and
  // CompareWidget.tsx. A ref, not React state, for the same reason as telemetryRef: this can
  // be touched many times per second across ~20 drivers during a fast replay.
  const lapMetricHistoryRef = useRef<Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>>({
    sector1: {},
    sector2: {},
    sector3: {},
    lapTime: {},
  });
  // Each driver's latest known NumberOfLaps, kept in lockstep with telemetryRef so
  // CompareWidget's continuous (speed/throttle/brake) charts can tag each buffered sample
  // with the lap it was captured on - telemetry itself carries no lap number, only
  // TimingData does, and the two arrive as independent, asynchronous SSE streams. A ref
  // (not state) for the same reason as telemetryRef: read every animation frame, not
  // through a render.
  const currentLapRef = useRef<Record<number, number>>({});
  // Pit stop / tyre change / penalty markers accumulated across the whole session, per
  // driver - see CompareWidget.tsx's event-marker overlay. A ref, not React state, for the
  // same reason as the others above: touched from three independent SSE handlers below and
  // read every animation frame's worth of polling inside CompareWidget, not through a render.
  const driverEventsRef = useRef<Record<number, DriverEventMarker[]>>({});
  // "Last known NumberOfPitStops per driver" - TimingData resends each driver's full current
  // resolved state on every message (not a delta), so a pit-stop event must only fire when
  // this count genuinely increases from what we last saw, never from "count > 0" (which
  // would refire on every single unrelated TimingData message once a driver has pitted).
  const lastSeenPitStopsRef = useRef<Record<number, number>>({});
  // "Highest TimingAppDataInfo.Stints index seen per driver" - a stint key we haven't seen
  // before means a tyre change happened (see TimingAppData handler below). Seeded from the
  // initial snapshot so the driver's starting tyre isn't itself misreported as a "change".
  const highestStintIndexRef = useRef<Record<number, number>>({});
  // Race control message keys already scanned for a penalty - RaceControlMessages resends
  // full state, and message keys are stable, so this prevents re-scanning (and thus
  // re-detecting, were addDriverEvent's own dedup not already a backstop) the same entry.
  const seenRaceControlKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!streamId) return;

    // Resets every piece of session state/refs when navigating between different live
    // streams (React Router reuses this component across a param-only route change rather
    // than remounting it) - deliberate, not derivable.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(INITIAL_STATE);
    telemetryRef.current = {};
    positionsRef.current = {};
    trailRef.current = {};
    lapMetricHistoryRef.current = { sector1: {}, sector2: {}, sector3: {}, lapTime: {} };
    currentLapRef.current = {};
    driverEventsRef.current = {};
    lastSeenPitStopsRef.current = {};
    highestStintIndexRef.current = {};
    seenRaceControlKeysRef.current = new Set();
    clearLiveRoster();
    setTeamRadioClips([]);
    setConnected(true);
    setHasPositionData(false);
    setHasTelemetryData(false);

    // Shared between the snapshot handler's one-time historical backfill (below) and the
    // live RaceControlMessages handler further down - a message's driver/lap/text are fully
    // known from the entry alone (unlike pit stops/stints, whose *history* isn't
    // reconstructable from a snapshot's cumulative-count-only fields), so it's safe to
    // extract genuine penalty events from race control messages the very first time each
    // message key is seen, whether that's in the initial snapshot or a later live message.
    const scanRaceControlEntriesForPenalties = (entries: Record<string, RaceControlEntry>) => {
      for (const [key, entry] of Object.entries(entries)) {
        if (seenRaceControlKeysRef.current.has(key)) continue;
        seenRaceControlKeysRef.current.add(key);
        if (!entry.Message || !isPenaltyMessage(entry.Message)) continue;
        const driverNumber = extractPenaltyDriverNumber(entry.Message);
        if (driverNumber === null) continue;
        addDriverEvent(driverEventsRef.current, driverNumber, {
          lap: entry.Lap ?? 0,
          kind: "penalty",
          label: formatPenaltyLabel(entry.Message),
        });
      }
    };

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
        scanRaceControlEntriesForPenalties(snapshot.race_control_messages);
      },
      driver_roster: (data) => {
        if (data.driver_roster) applyRosterWire(data.driver_roster);
      },
      TimingData: (data) => {
        if (data.drivers) {
          // Each entry is the full current resolved DriverTiming for that driver (not a
          // partial patch - see diff_to_wire), so Sectors/LastLapTime/SectorsLap/
          // NumberOfLaps are always safe to read directly whenever present. Accumulate any
          // new per-lap sector/lap-time values into lapMetricHistoryRef (a ref, mutated
          // directly - see the field's own comment) alongside the existing setState merge.
          for (const [driverStr, driver] of Object.entries(data.drivers)) {
            const driverNumber = Number(driverStr);

            if (typeof driver.NumberOfLaps === "number") {
              currentLapRef.current[driverNumber] = driver.NumberOfLaps;
            }

            if (typeof driver.NumberOfPitStops === "number") {
              const lastSeen = lastSeenPitStopsRef.current[driverNumber];
              // Only a genuine increase over the last value we saw counts as "just
              // pitted" - TimingData resends every driver's full current resolved state on
              // every message (not a delta), so testing e.g. "> 0" here would refire this
              // event on every unrelated message once a driver has pitted at all.
              if (lastSeen !== undefined && driver.NumberOfPitStops > lastSeen) {
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
          // instead, same convention SectorsLap already uses elsewhere in this file.
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
          scanRaceControlEntriesForPenalties(data.race_control_messages);
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
          positionsRef.current = { ...positionsRef.current, ...data.positions };
          for (const [driverStr, pos] of Object.entries(data.positions)) {
            const trail = trailRef.current[driverStr] ?? (trailRef.current[driverStr] = []);
            trail.push({ x: pos.x, y: pos.y });
            if (trail.length > MAX_TRAIL_POINTS_PER_DRIVER) trail.shift();
          }
          setHasPositionData(true);
        }
      },
      RADIO_CLIP_READY: () => setRadioRefreshSignal((n) => n + 1),
      RADIO_TRANSCRIPT_READY: () => setRadioRefreshSignal((n) => n + 1),
      RADIO_ANALYSIS_READY: () => setRadioRefreshSignal((n) => n + 1),
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
  }, [streamId]);

  // Lifted up (rather than fetched privately inside TeamRadioPanel, as it originally was)
  // so TimingTower's per-row radio indicator and TeamRadioPanel can share the exact
  // same data instead of each running their own fetch against the same endpoint.
  const sessionKey = state.sessionKey;
  const refetchTeamRadio = useCallback(async () => {
    if (sessionKey == null) return;
    try {
      setTeamRadioClips(await getTeamRadioForSession(sessionKey));
    } catch (err) {
      console.error("Failed to fetch team radio", err);
    }
  }, [sessionKey]);

  useEffect(() => {
    // refetchTeamRadio only sets state after an await (see above) - genuinely async, not a
    // synchronous effect-body setState; the linter's static analysis just can't see through
    // the function call to confirm that.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refetchTeamRadio();
  }, [refetchTeamRadio, radioRefreshSignal]);

  const toggleDriver = (driverNumber: number) => {
    setSelectedDrivers((prev) => {
      if (prev.includes(driverNumber)) return prev.filter((d) => d !== driverNumber);
      if (prev.length >= 4) return [...prev.slice(1), driverNumber];
      return [...prev, driverNumber];
    });
  };

  const addCompareWidget = () => {
    const id = `compare-${nextCompareWidgetId.current++}`;
    setCompareWidgets((prev) => [...prev, { id, metric: "speed" }]);
  };

  const updateCompareWidgetMetric = (id: string, metric: CompareMetric) => {
    setCompareWidgets((prev) => prev.map((w) => (w.id === id ? { ...w, metric } : w)));
  };

  const removeCompareWidget = (id: string) => {
    setCompareWidgets((prev) => prev.filter((w) => w.id !== id));
  };

  const meetingName = state.sessionInfo.Meeting?.Name;
  const sessionType = state.sessionInfo.Type;
  const isQualifying = sessionType === "Qualifying";

  return (
    <div className="race-mode">
      <div className="rm-header">
        <h1>
          <span className="display">Race Mode</span>
          {connected && <span className="rm-live-pill">LIVE</span>}
          {isQualifying && (
            <span className="rm-session-pill qualifying">
              QUALIFYING{state.qualifyingPart ? ` – ${state.qualifyingPart}` : ""}
            </span>
          )}
          {meetingName && (
            <span style={{ color: "var(--text-lo)", fontSize: 15, fontWeight: 400 }}>{meetingName}</span>
          )}
        </h1>
        <Link to="/" className="rm-back-link">
          &larr; Back to Garage
        </Link>
      </div>

      <div className="rm-grid">
        <div className="rm-panel" ref={timingTowerPanelRef}>
          <div className="rm-panel-label">
            <span>Timing Tower</span>
          </div>
          <SessionClock
            lapCount={state.lapCount}
            extrapolatedClock={state.extrapolatedClock}
            isQualifying={isQualifying}
            qualifyingPart={state.qualifyingPart}
          />
          <div style={{ height: 14 }} />
          <TimingTower
            drivers={state.drivers}
            timingAppData={state.timingAppData}
            timingStats={state.timingStats}
            battleRadar={state.battleRadar}
            tyreStrategyPredictions={state.tyreStrategyPredictions}
            teamRadioClips={teamRadioClips}
            selectedDrivers={selectedDrivers}
            onToggleDriver={toggleDriver}
            isQualifying={isQualifying}
            eliminatedDrivers={state.eliminatedDrivers}
            qualifyingGaps={state.qualifyingGaps}
          />
        </div>

        {/* Bundled into one flex-column rail, pinned via ResizeObserver (see
            timingTowerHeight above) to exactly the Timing Tower panel's rendered height -
            a CSS-only grid-stretch approach can't do this (see the comment on
            timingTowerHeight for why). Track Map/Track Status/Telemetry Compare keep their
            natural height; Team Radio (.rm-panel-fill) is the one item that flexes to
            absorb whatever height is left over, scrolling internally instead of pushing
            the rail past the tower's bottom edge. */}
        <div className="rm-right-rail" style={{ height: timingTowerHeight ?? undefined }}>
          {hasPositionData && (
            <div className="rm-panel">
              <div className="rm-panel-label">Track Map</div>
              <TrackMap positionsRef={positionsRef} trailRef={trailRef} selectedDrivers={selectedDrivers} />
            </div>
          )}

          <div className="rm-panel">
            <div className="rm-panel-label">Track Status &amp; Weather</div>
            <TrackStatusBanner trackStatus={state.trackStatus} weather={state.weather} />
          </div>

          {/* Not gated on hasTelemetryData - unlike the old fixed-3-band TelemetryLab,
              some of this panel's metrics (sector times, lap time) come from TimingData,
              not CarData.z, and must work even in a session where CarData.z/Position.z
              never arrive at all (a separate, already-diagnosed F1TV auth/entitlement
              issue - see hasTelemetryData's own comment). */}
          <div className="rm-panel">
            <div className="rm-panel-label">
              <span>Telemetry Compare</span>
              <button className="add-compare-btn" type="button" onClick={addCompareWidget}>
                + Add Compare
              </button>
            </div>
            {compareWidgets.map((w) => (
              <CompareWidget
                key={w.id}
                metric={w.metric}
                onMetricChange={(m) => updateCompareWidgetMetric(w.id, m)}
                onRemove={() => removeCompareWidget(w.id)}
                selectedDrivers={selectedDrivers}
                telemetryRef={telemetryRef}
                lapMetricHistoryRef={lapMetricHistoryRef}
                currentLapRef={currentLapRef}
                driverEventsRef={driverEventsRef}
              />
            ))}
          </div>

          <div className="rm-panel rm-panel-fill">
            <div className="rm-panel-label">Team Radio</div>
            <TeamRadioPanel clips={teamRadioClips} />
          </div>
        </div>

        {hasTelemetryData && hasPositionData && (
          <div className="rm-panel rm-span-2">
            <div className="rm-panel-label">Lap Delta &amp; Corner Analysis</div>
            <LapDeltaChart sessionKey={state.sessionKey} selectedDrivers={selectedDrivers} drivers={state.drivers} />
          </div>
        )}

        <div className="rm-panel rm-span-2">
          <div className="rm-panel-label">Race Control</div>
          <RaceControlFeed messages={state.raceControlMessages} />
        </div>
      </div>
    </div>
  );
};

export default RaceMode;
