import React, { useEffect, useRef, useState } from "react";
import { ExtrapolatedClockData, LapCountData } from "../../types/raceMode";

interface SessionClockProps {
  lapCount: LapCountData;
  extrapolatedClock: ExtrapolatedClockData;
  /** Qualifying has no lap count worth showing (F1 never sends LapCount for it - laps
   * exist but "lap N of total" is a race-only framing), and time-remaining is scoped to
   * the current segment rather than the whole session - see qualifyingPart. */
  isQualifying: boolean;
  qualifyingPart: string | null;
  /** SessionInfo.StartDate/GmtOffset - see computeSessionStartUtcMs. Used only to show a
   * "Starts In" countdown before the session goes live; omit or leave undefined once
   * that's no longer relevant. */
  startDate?: string;
  gmtOffset?: string;
}

/** Parse F1's "H:MM:SS" (or "MM:SS") remaining-time string into total seconds. */
function parseHms(value: string): number | null {
  const parts = value.split(":").map(Number);
  if (parts.some((p) => Number.isNaN(p))) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return null;
}

function formatHms(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(clamped / 3600);
  const m = Math.floor((clamped % 3600) / 60);
  const s = clamped % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Parses a SignalR GmtOffset string ("02:00:00", possibly "-05:00:00") into milliseconds. */
function parseGmtOffsetMs(offset: string): number | null {
  const match = offset.match(/^(-)?(\d+):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const sign = match[1] === "-" ? -1 : 1;
  const [, , hours, minutes, seconds] = match;
  return sign * ((Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds)) * 1000);
}

/** SessionInfo's StartDate is the circuit's local wall-clock scheduled start time - it
 * carries no timezone of its own, so GmtOffset (the circuit's UTC offset) is what turns
 * it into an actual, comparable UTC instant: UTC = local - offset. */
function computeSessionStartUtcMs(startDate?: string, gmtOffset?: string): number | null {
  if (!startDate) return null;
  const localMs = Date.parse(startDate.endsWith("Z") ? startDate : `${startDate}Z`);
  if (Number.isNaN(localMs)) return null;
  const offsetMs = gmtOffset ? parseGmtOffsetMs(gmtOffset) : null;
  return offsetMs != null ? localMs - offsetMs : localMs;
}

/**
 * F1's ExtrapolatedClock topic is sent rarely - observed exactly once in a
 * full captured race - and carries `Extrapolating: true` as an explicit
 * instruction that the client should keep counting the clock down locally
 * between updates, not wait for the server to send fresh values. This
 * anchors on each new value received and ticks it down with a local
 * interval, re-anchoring whenever a fresher value arrives.
 *
 * The anchor time is F1's own `Utc` timestamp for that Remaining value, not the moment
 * this component happened to receive/render it - using Date.now() as the anchor was a
 * real bug: a page refresh (or SSE reconnect) re-delivers the same last-known Remaining
 * value via the snapshot, and anchoring to "now" made the countdown restart from that
 * stale number instead of continuing from the true current remaining time. Confirmed live
 * (e.g. Remaining="00:12:59" as of Utc=14:47:01 was still being shown as ~12:59 minutes
 * later on refresh, instead of counting down to ~06:59).
 */
const SessionClock: React.FC<SessionClockProps> = ({
  lapCount,
  extrapolatedClock,
  isQualifying,
  qualifyingPart,
  startDate,
  gmtOffset,
}) => {
  const [displayedRemaining, setDisplayedRemaining] = useState<string>("--:--:--");
  const [startsIn, setStartsIn] = useState<string | null>(null);
  const anchorRef = useRef<{ seconds: number; receivedAtMs: number } | null>(null);

  useEffect(() => {
    if (!extrapolatedClock.Remaining) return;
    const seconds = parseHms(extrapolatedClock.Remaining);
    if (seconds == null) return;

    // Extrapolating: false is F1 explicitly saying this value is static - the session
    // hasn't started (or is between segments) and there's nothing to extrapolate yet.
    // Treating it as a live anchor and subtracting wall-clock time since receipt was a
    // real bug: on the pre-race snapshot (Remaining "02:00:00" as of some now-past Utc),
    // it silently decayed the untouched 2-hour duration by however long ago that message
    // arrived, then froze on that wrong number since no ticking interval runs.
    if (!extrapolatedClock.Extrapolating) {
      anchorRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDisplayedRemaining(formatHms(seconds));
      return;
    }

    const utcMs = extrapolatedClock.Utc ? Date.parse(extrapolatedClock.Utc) : NaN;
    const receivedAtMs = Number.isNaN(utcMs) ? Date.now() : utcMs;
    anchorRef.current = { seconds, receivedAtMs };
    // Re-anchoring the displayed countdown to a fresh server-pushed clock value is exactly
    // the "subscribe to an external system" case React's own effect guidelines describe as
    // legitimate - the external system here being F1's ExtrapolatedClock feed plus wall time.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDisplayedRemaining(formatHms(seconds - (Date.now() - receivedAtMs) / 1000));
  }, [extrapolatedClock.Remaining, extrapolatedClock.Utc, extrapolatedClock.Extrapolating]);

  useEffect(() => {
    if (!extrapolatedClock.Extrapolating) return;
    const interval = setInterval(() => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const elapsedSeconds = (Date.now() - anchor.receivedAtMs) / 1000;
      setDisplayedRemaining(formatHms(anchor.seconds - elapsedSeconds));
    }, 1000);
    return () => clearInterval(interval);
  }, [extrapolatedClock.Extrapolating]);

  useEffect(() => {
    const startUtcMs = computeSessionStartUtcMs(startDate, gmtOffset);
    if (startUtcMs == null) {
      setStartsIn(null);
      return;
    }
    const tick = () => {
      const remainingMs = startUtcMs - Date.now();
      // Once the scheduled start time has passed, this countdown has nothing left to
      // say - the real ExtrapolatedClock/lap-count display above takes over.
      setStartsIn(remainingMs > 0 ? formatHms(remainingMs / 1000) : null);
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [startDate, gmtOffset]);

  // Extrapolating: false mid-session (not still counting down to a scheduled start, and
  // not just "no data yet") means F1 itself has stopped this clock - a red flag being the
  // real-world case that prompted this. Surfaced explicitly so a frozen number reads as
  // "paused on purpose" rather than looking like the UI has silently stalled.
  const isPaused = !extrapolatedClock.Extrapolating && !startsIn && displayedRemaining !== "--:--:--";

  return (
    <div className="rm-clock">
      {isQualifying ? (
        <div>
          <div className="big mono qualifying-part">{qualifyingPart ?? "Q?"}</div>
          <div className="lbl">Session</div>
        </div>
      ) : (
        <div>
          <div className="big mono">
            {lapCount.CurrentLap ?? "-"}
            {lapCount.TotalLaps ? ` / ${lapCount.TotalLaps}` : ""}
          </div>
          <div className="lbl">Lap</div>
        </div>
      )}
      <div>
        <div className="big mono">{displayedRemaining}</div>
        <div className="lbl">
          {isQualifying ? `Time Remaining${qualifyingPart ? ` (${qualifyingPart})` : ""}` : "Remaining"}
          {isPaused && <span className="rm-paused-pill">Paused</span>}
        </div>
      </div>
      {startsIn && (
        <div>
          <div className="big mono">{startsIn}</div>
          <div className="lbl">Starts In</div>
        </div>
      )}
    </div>
  );
};

export default SessionClock;
