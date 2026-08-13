import React from "react";
import { TrackStatus, Weather } from "../../types/raceMode";

interface TrackStatusBannerProps {
  trackStatus: TrackStatus;
  weather: Weather;
}

/**
 * Track status codes observed directly in captured logs: "1" -> AllClear, "2" -> Yellow.
 * The other codes below (safety car / red / VSC) follow F1's commonly documented
 * numbering but weren't directly observed in this project's captures - the banner
 * always shows the real Message text regardless, so an imperfect color mapping for
 * an unconfirmed code degrades to "status-unknown" rather than showing something wrong.
 */
function flagClass(status?: string): string {
  switch (status) {
    case "1":
      return "status-green";
    case "2":
    case "6":
    case "7":
      return "status-yellow";
    case "4":
    case "5":
      return "status-red";
    default:
      return "status-unknown";
  }
}

const TrackStatusBanner: React.FC<TrackStatusBannerProps> = ({ trackStatus, weather }) => (
  <div>
    <div className={`flag-banner ${flagClass(trackStatus.Status)}`}>{trackStatus.Message ?? "Unknown"}</div>
    <div className="rm-strip">
      <div className="rm-strip-item">
        <span className="v mono">{weather.TrackTemp ?? "–"}°</span>
        <span className="l">Track</span>
      </div>
      <div className="rm-strip-item">
        <span className="v mono">{weather.AirTemp ?? "–"}°</span>
        <span className="l">Air</span>
      </div>
      <div className="rm-strip-item">
        <span className="v mono">{weather.Humidity ?? "–"}%</span>
        <span className="l">Humidity</span>
      </div>
      <div className="rm-strip-item">
        <span className="v mono">{weather.WindSpeed ?? "–"}</span>
        <span className="l">Wind km/h</span>
      </div>
      <div className="rm-strip-item">
        <span className="v mono">{weather.Rainfall === "1" ? "Wet" : "Dry"}</span>
        <span className="l">Rainfall</span>
      </div>
    </div>
  </div>
);

export default TrackStatusBanner;
