/**
 * Types for the Race Mode live view.
 *
 * These mirror the *resolved* wire format the backend's diff_to_wire()
 * (utils/live_session_pipeline.py) actually sends over SSE - already-merged
 * current state for whatever changed, not a raw diff. Frontend "merging" is
 * therefore just a shallow per-driver overwrite, never a deep merge - the
 * backend already did that work.
 */
import type { DriverRosterWireEntry } from "../data/driverRoster";

export interface DriverTiming {
  Position?: string;
  GapToLeader?: string;
  IntervalToPositionAhead?: { Value?: string };
  /** Race-only fields (GapToLeader/IntervalToPositionAhead) are never sent during
   * qualifying (confirmed live: 0 occurrences over a full session) - Stats["0"].TimeDiffToFastest
   * is the qualifying-relevant gap instead (gap to the session's fastest lap so far). */
  Stats?: Record<string, { TimeDiffToFastest?: string; TimeDifftoPositionAhead?: string }>;
  NumberOfLaps?: number;
  LastLapTime?: { Value?: string; OverallFastest?: boolean; PersonalFastest?: boolean };
  BestLapTime?: { Value?: string; Lap?: number };
  Sectors?: Record<
    string,
    { Value?: string; OverallFastest?: boolean; PersonalFastest?: boolean; Segments?: Record<string, { Status?: number }> }
  >;
  /** The driver's lap count at the moment Sectors last changed - race mode only, shown as a
   * small "as of lap N" marker since sector splits update independently of NumberOfLaps and
   * can otherwise look like they belong to whatever lap is currently displayed elsewhere. */
  SectorsLap?: number;
  Speeds?: Record<string, { Value?: string; OverallFastest?: boolean; PersonalFastest?: boolean }>;
  InPit?: boolean;
  PitOut?: boolean;
  NumberOfPitStops?: number;
  Retired?: boolean;
  Stopped?: boolean;
  Line?: number;
}

export interface DriverListInfo {
  Line?: number;
}

export interface StintInfo {
  Compound?: string;
  TotalLaps?: number;
  New?: string;
}

export interface TimingAppDataInfo {
  Stints?: Record<string, StintInfo>;
  GridPos?: string;
}

/** One resolved tyre stint for display, derived from TimingAppDataInfo.Stints - see
 * TimingTower.tsx's compoundHistory(). Shared between TimingTower and TyreStintIndicator. */
export interface StintEntry {
  compound: string;
  /** Laps completed on this set of tyres so far (F1's own Stints[i].TotalLaps, live-updating
   * for the current stint) - undefined only if F1 hasn't sent a lap count for this stint yet. */
  laps?: number;
}

export interface TimingStatsInfo {
  BestSpeeds?: Record<string, { Position?: number; Value?: string }>;
  PersonalBestLapTime?: { Value?: string };
}

export interface TopThreeInfo {
  DiffToLeader?: string;
}

export interface TrackStatus {
  Status?: string;
  Message?: string;
}

export interface Weather {
  AirTemp?: string;
  TrackTemp?: string;
  Humidity?: string;
  Pressure?: string;
  Rainfall?: string;
  WindSpeed?: string;
  WindDirection?: string;
}

export interface SessionInfoData {
  Meeting?: { Key?: number; Name?: string; Location?: string; Country?: { Name?: string } };
  Key?: number;
  Type?: string;
  Name?: string;
}

export interface LapCountData {
  CurrentLap?: number;
  TotalLaps?: number;
}

export interface ExtrapolatedClockData {
  Remaining?: string;
  Extrapolating?: boolean;
  /** When F1 captured this Remaining value (ISO 8601, UTC) - the anchor for local
   * countdown ticking must use this, not the moment the browser received/rendered it,
   * or a page refresh (which re-delivers this same last-known value via the SSE
   * snapshot) would restart the countdown from a stale number instead of the true
   * current remaining time - see SessionClock.tsx. */
  Utc?: string;
}

export interface RaceControlEntry {
  Utc?: string;
  Lap?: number;
  Category?: string;
  Message?: string;
  Flag?: string;
  Status?: string;
  Scope?: string;
  RacingNumber?: string;
}

export interface TelemetrySample {
  speed_kmh: number;
  rpm: number;
  gear: number;
  throttle_pct: number;
  brake_pct: number;
  drs: number;
}

export interface PositionSample {
  x: number;
  y: number;
  z: number;
  status: string;
}

export interface BattleRadarLapGap {
  lap_number: number;
  gap_seconds: number;
}

/** Mirrors SessionState.battle_radar entries (utils/session_state.py). Only ever present
 * for a driver who is both within threshold AND confirmed closing over >=2 laps - see
 * _update_battle_radar's trend check on the backend. */
export interface BattleRadarAlert {
  driver_number: number;
  ahead_driver_number: number | null;
  gap_seconds: number;
  alert_level: "battle" | "upcoming";
  lap_history: BattleRadarLapGap[];
}

/** Mirrors utils/tyre_strategy_prediction.PredictedStint - one stint in a Gemini-predicted
 * remaining strategy, from the stint currently on the car through to the finish. */
export interface PredictedStintWire {
  stint_number: number;
  compound: "soft" | "medium" | "hard" | "intermediate" | "wet";
  predicted_total_laps: number;
}

/** Mirrors SessionState.tyre_strategy_predictions entries (utils/session_state.py) - race
 * mode only, refreshed once per driver per completed lap by a Strands Agent/Gemini call
 * (see utils/tyre_strategy_prediction.py). Never present during qualifying. */
export interface TyreStrategyPredictionWire {
  driver_number: number;
  generated_at_lap: number;
  predicted_stints: PredictedStintWire[];
  safety_car_note: string;
  summary: string;
}

export interface CompletedLapWire {
  driver_number: number;
  lap_number: number;
  lap_duration_seconds: number | null;
  avg_speed_kmh: number | null;
  max_speed_kmh: number | null;
  avg_throttle_pct: number | null;
  drs_active_pct: number | null;
}

export interface NewRadioCaptureWire {
  driver_number: number;
  lap_number: number | null;
  /** Which qualifying segment this was captured in (e.g. "Q2") - null for a race/practice
   * session, or a capture that arrived before SessionInfo established the session type. */
  qualifying_part: string | null;
  utc: string;
}

export type RadioClipStatus =
  | "pending"
  | "downloading"
  | "downloaded"
  | "transcribing"
  | "done"
  | "failed_download"
  | "failed_transcription";

export type RadioSpeakerRole = "driver" | "pit_wall" | "unclear";

export interface TeamRadioClip {
  id: number;
  session_key: number;
  driver_number: number;
  lap_number: number | null;
  /** Which qualifying segment this was captured in (e.g. "Q2") - null for a race/practice
   * session. Prefer this over lap_number for display during qualifying, where a raw lap
   * count is a session-cumulative number, not a meaningful "current lap". */
  qualifying_part: string | null;
  ts: string;
  audio_path: string | null;
  transcript: string | null;
  status: RadioClipStatus;
  error: string | null;
  transcribed_at: string | null;
  /** Gemini-classified, null until analysis completes - speaker_role is an LLM inference
   * over the transcript text, not ground truth (F1's raw feed carries no speaker info). */
  speaker_role: RadioSpeakerRole | null;
  is_notable: boolean | null;
  notable_reason: string | null;
}

export interface LapTraceData {
  driver_number: number;
  lap_number: number;
  distance_m: number[];
  speed_kmh: number[];
  throttle_pct: number[];
  brake_pct: number[];
  acceleration_ms2: number[];
}

export interface CornerData {
  distance_m: number;
  apex_speed_kmh: number;
}

export interface DeltaTraceData {
  distance_m: number[];
  delta_seconds: number[];
  corners: CornerData[];
}

export interface LapComparisonData {
  session_key: number;
  driver_a: LapTraceData;
  driver_b: LapTraceData;
  delta: DeltaTraceData;
}

/** The full-state payload sent as the SSE "snapshot" event, matching SessionState.snapshot(). */
export interface RaceModeSnapshot {
  session_key: number | null;
  drivers: Record<string, DriverTiming>;
  driver_list: Record<string, DriverListInfo>;
  timing_app_data: Record<string, TimingAppDataInfo>;
  timing_stats: Record<string, TimingStatsInfo>;
  top_three: Record<string, TopThreeInfo>;
  track_status: TrackStatus;
  weather: Weather;
  session_info: SessionInfoData;
  session_data: Record<string, unknown>;
  session_status: Record<string, unknown>;
  lap_count: LapCountData;
  extrapolated_clock: ExtrapolatedClockData;
  race_control_messages: Record<string, RaceControlEntry>;
  driver_roster: Record<string, DriverRosterWireEntry>;
  battle_radar: Record<string, BattleRadarAlert>;
  tyre_strategy_predictions: Record<string, TyreStrategyPredictionWire>;
  /** "Q1"/"Q2"/"Q3" for a qualifying session, null otherwise or before the first
   * segment is known - see SessionState.qualifying_part (utils/session_state.py). */
  qualifying_part: string | null;
  /** Driver numbers knocked out at the end of a previous qualifying segment - permanent
   * for the rest of the session once added. See SessionState.eliminated_drivers. */
  eliminated_drivers: number[];
  /** Gap to the session-best lap this qualifying part, in seconds (0 for the leader) -
   * computed backend-side from BestLapTime, never from F1's own Stats field (unreliable -
   * see SessionState._recompute_qualifying_gaps). Absent key = no valid lap yet. */
  qualifying_gaps: Record<string, number>;
}
