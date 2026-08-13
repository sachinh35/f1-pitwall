/**
 * Typed EventSource wrapper for the Race Mode live feed
 * (GET /live/{streamId}/events).
 *
 * Chosen over WebSocket because the traffic is almost entirely
 * server -> client, and EventSource gives automatic reconnect (plus
 * Last-Event-ID resume, handled natively by the browser) for free - see the
 * product investigation artifact's SSE-vs-WebSocket discussion.
 */
import type { DriverRosterWireEntry } from "../data/driverRoster";
import {
  BattleRadarAlert,
  CompletedLapWire,
  DriverListInfo,
  DriverTiming,
  ExtrapolatedClockData,
  LapCountData,
  NewRadioCaptureWire,
  PositionSample,
  RaceControlEntry,
  RaceModeSnapshot,
  SessionInfoData,
  TelemetrySample,
  TimingAppDataInfo,
  TimingStatsInfo,
  TopThreeInfo,
  TrackStatus,
  TyreStrategyPredictionWire,
  Weather,
} from "../types/raceMode";

export interface RaceModeEventMap {
  snapshot: RaceModeSnapshot;
  TimingData: {
    drivers?: Record<string, DriverTiming>;
    completed_laps?: CompletedLapWire[];
    // null for a driver means their previously-active alert just cleared - see diff_to_wire.
    battle_radar?: Record<string, BattleRadarAlert | null>;
    // Full table (all drivers, not just this diff's changed ones) - see
    // SessionState.qualifying_gaps / _recompute_qualifying_gaps. A driver with no valid
    // best lap yet has no entry - never inferred as "not present == leader".
    qualifying_gaps?: Record<string, number>;
  };
  DriverList: { driver_list?: Record<string, DriverListInfo> };
  TimingAppData: { timing_app_data?: Record<string, TimingAppDataInfo> };
  TimingStats: { timing_stats?: Record<string, TimingStatsInfo> };
  TopThree: { top_three?: Record<string, TopThreeInfo> };
  TrackStatus: { track_status?: TrackStatus };
  WeatherData: { weather?: Weather };
  SessionInfo: {
    session_info?: SessionInfoData;
    // See SessionData's identical fields - also sent here because qualifying_part can
    // default to "Q1" the moment SessionInfo reveals Type "Qualifying" (F1 never
    // announces Q1 explicitly - see SessionState._apply_session_info).
    qualifying_part?: string | null;
    eliminated_drivers?: number[];
  };
  SessionData: {
    session_data?: Record<string, unknown>;
    qualifying_part?: string | null;
    eliminated_drivers?: number[];
  };
  LapCount: { lap_count?: LapCountData };
  ExtrapolatedClock: { extrapolated_clock?: ExtrapolatedClockData };
  RaceControlMessages: { race_control_messages?: Record<string, RaceControlEntry> };
  driver_roster: { driver_roster?: Record<string, DriverRosterWireEntry> };
  "CarData.z": { telemetry?: Record<string, TelemetrySample> };
  "Position.z": { positions?: Record<string, PositionSample> };
  TeamRadio: { new_radio_captures?: NewRadioCaptureWire[] };
  RADIO_CLIP_READY: { row_id: number };
  RADIO_TRANSCRIPT_READY: { row_id: number };
  RADIO_ANALYSIS_READY: { row_id: number };
  TYRE_STRATEGY_PREDICTION: { driver_number: number; prediction: TyreStrategyPredictionWire };
}

export type RaceModeEventName = keyof RaceModeEventMap;

export type RaceModeHandlers = {
  [K in RaceModeEventName]?: (data: RaceModeEventMap[K]) => void;
};

const API_BASE_URL = "http://localhost:8000";

/**
 * Open the SSE connection for a stream and wire up typed per-event handlers.
 * Returns a cleanup function that closes the connection - call it from a
 * useEffect cleanup.
 */
export function connectRaceModeStream(streamId: string, handlers: RaceModeHandlers): () => void {
  const source = new EventSource(`${API_BASE_URL}/live/${streamId}/events`);

  (Object.keys(handlers) as RaceModeEventName[]).forEach((eventName) => {
    const handler = handlers[eventName];
    if (!handler) return;

    source.addEventListener(eventName, (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      try {
        const data = JSON.parse(messageEvent.data);
        handler(data);
      } catch (err) {
        console.error(`Failed to parse SSE event "${eventName}"`, err);
      }
    });
  });

  source.onerror = () => {
    // EventSource reconnects automatically (with Last-Event-ID) - nothing to do here
    // beyond logging, unless readyState is CLOSED (server told us not to retry).
    if (source.readyState === EventSource.CLOSED) {
      console.warn(`SSE stream for ${streamId} closed - session likely finished`);
    }
  };

  return () => source.close();
}
