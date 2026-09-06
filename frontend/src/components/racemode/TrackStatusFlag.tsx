import React from "react";
import { SessionStatusData, TrackStatus } from "../../types/raceMode";
import { resolveFlagDisplay } from "../../utils/trackStatus";

interface TrackStatusFlagProps {
  trackStatus: TrackStatus;
  sessionStatus?: SessionStatusData;
}

/**
 * Compact flag pill for prominent placement next to the session clock, at the top of
 * the page - a red flag or safety car is urgent enough that it shouldn't require
 * scrolling down to the full Track Status & Weather panel (TrackStatusBanner) to see.
 * That panel still exists and still shows the same flag alongside weather; this is a
 * second, always-visible copy of just the flag, not a replacement.
 */
const TrackStatusFlag: React.FC<TrackStatusFlagProps> = ({ trackStatus, sessionStatus }) => {
  const { text, className } = resolveFlagDisplay(trackStatus, sessionStatus);
  return <div className={`flag-banner flag-banner-top ${className}`}>{text}</div>;
};

export default TrackStatusFlag;
