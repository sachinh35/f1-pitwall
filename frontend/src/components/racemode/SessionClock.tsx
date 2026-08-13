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
const SessionClock: React.FC<SessionClockProps> = ({ lapCount, extrapolatedClock, isQualifying, qualifyingPart }) => {
  const [displayedRemaining, setDisplayedRemaining] = useState<string>("--:--:--");
  const anchorRef = useRef<{ seconds: number; receivedAtMs: number } | null>(null);

  useEffect(() => {
    if (!extrapolatedClock.Remaining) return;
    const seconds = parseHms(extrapolatedClock.Remaining);
    if (seconds == null) return;
    const utcMs = extrapolatedClock.Utc ? Date.parse(extrapolatedClock.Utc) : NaN;
    const receivedAtMs = Number.isNaN(utcMs) ? Date.now() : utcMs;
    anchorRef.current = { seconds, receivedAtMs };
    // Re-anchoring the displayed countdown to a fresh server-pushed clock value is exactly
    // the "subscribe to an external system" case React's own effect guidelines describe as
    // legitimate - the external system here being F1's ExtrapolatedClock feed plus wall time.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDisplayedRemaining(formatHms(seconds - (Date.now() - receivedAtMs) / 1000));
  }, [extrapolatedClock.Remaining, extrapolatedClock.Utc]);

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
        <div className="lbl">{isQualifying ? `Time Remaining${qualifyingPart ? ` (${qualifyingPart})` : ""}` : "Remaining"}</div>
      </div>
    </div>
  );
};

export default SessionClock;
