import React from "react";
import { SessionStatusData, TrackStatus, Weather } from "../../types/raceMode";
import { resolveFlagDisplay } from "../../utils/trackStatus";

interface TrackStatusBannerProps {
  trackStatus: TrackStatus;
  sessionStatus?: SessionStatusData;
  weather: Weather;
}

const TrackStatusBanner: React.FC<TrackStatusBannerProps> = ({ trackStatus, sessionStatus, weather }) => {
  const { text, className } = resolveFlagDisplay(trackStatus, sessionStatus);
  return (
    <div>
      <div className={`flag-banner ${className}`}>{text}</div>
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
};

export default TrackStatusBanner;
