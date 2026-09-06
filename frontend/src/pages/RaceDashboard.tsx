import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import CompareWidget from "../components/racemode/CompareWidget";
import LapDeltaChart from "../components/racemode/LapDeltaChart";
import RaceControlFeed from "../components/racemode/RaceControlFeed";
import SessionClock from "../components/racemode/SessionClock";
import TeamRadioPanel from "../components/racemode/TeamRadioPanel";
import TimingTower from "../components/racemode/TimingTower";
import TrackMap from "../components/racemode/TrackMap";
import TrackStatusBanner from "../components/racemode/TrackStatusBanner";
import TrackStatusFlag from "../components/racemode/TrackStatusFlag";
import { useCompareWidgets } from "../hooks/useCompareWidgets";
import { useDriverSelection } from "../hooks/useDriverSelection";
import { LiveSessionState } from "../hooks/useLiveSessionState";
import "../styles/raceMode.css";

interface RaceDashboardProps {
  session: LiveSessionState;
}

/**
 * The race-specific live view: Timing Tower shows each driver's last lap, gap-to-leader
 * and interval-ahead (race concepts F1 never sends during qualifying), with no Qualifying
 * Results panel. Deliberately has its own full layout, not a shared one with
 * QualifyingDashboard - see that component's docstring for why.
 */
const RaceDashboard: React.FC<RaceDashboardProps> = ({ session }) => {
  const { state, connected, hasPositionData, hasTelemetryData, teamRadioClips, refs } = session;
  const { selectedDrivers, toggleDriver } = useDriverSelection();
  const { compareWidgets, addCompareWidget, updateCompareWidgetMetric, removeCompareWidget } = useCompareWidgets();

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
    /* v8 ignore next -- the ref is always set once this effect runs post-mount; defensive only */
    if (!el) return;
    const observer = new ResizeObserver((entries) => setTimingTowerHeight(entries[0].contentRect.height));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const meetingName = state.sessionInfo.Meeting?.Name;

  return (
    <div className="race-mode">
      <div className="rm-header">
        <h1>
          <span className="display">Race Mode</span>
          {connected && <span className="rm-live-pill">LIVE</span>}
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
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
            <SessionClock
              lapCount={state.lapCount}
              extrapolatedClock={state.extrapolatedClock}
              isQualifying={false}
              qualifyingPart={state.qualifyingPart}
              startDate={state.sessionInfo.StartDate}
              gmtOffset={state.sessionInfo.GmtOffset}
            />
            <TrackStatusFlag trackStatus={state.trackStatus} sessionStatus={state.sessionStatus} />
          </div>
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
            isQualifying={false}
            eliminatedDrivers={state.eliminatedDrivers}
            qualifyingGaps={state.qualifyingGaps}
          />
        </div>

        <div className="rm-right-rail" style={{ height: timingTowerHeight ?? undefined }}>
          {hasPositionData && (
            <div className="rm-panel">
              <div className="rm-panel-label">Track Map</div>
              <TrackMap positionsRef={refs.positionsRef} trailRef={refs.trailRef} selectedDrivers={selectedDrivers} />
            </div>
          )}

          <div className="rm-panel">
            <div className="rm-panel-label">Track Status &amp; Weather</div>
            <TrackStatusBanner trackStatus={state.trackStatus} sessionStatus={state.sessionStatus} weather={state.weather} />
          </div>

          <div className="rm-panel rm-panel-fill">
            <div className="rm-panel-label">Team Radio</div>
            <TeamRadioPanel clips={teamRadioClips} />
          </div>
        </div>

        <div className="rm-panel rm-span-2 rm-compare-panel-wide">
          <div className="rm-panel-label">
            <span>Telemetry Compare</span>
            <button className="add-compare-btn" type="button" onClick={addCompareWidget}>
              + Add Compare
            </button>
          </div>
          <div className="rm-compare-widgets-row">
            {compareWidgets.map((w) => (
              <CompareWidget
                key={w.id}
                metric={w.metric}
                onMetricChange={(m) => updateCompareWidgetMetric(w.id, m)}
                onRemove={() => removeCompareWidget(w.id)}
                selectedDrivers={selectedDrivers}
                telemetryRef={refs.telemetryRef}
                lapMetricHistoryRef={refs.lapMetricHistoryRef}
                currentLapRef={refs.currentLapRef}
                driverEventsRef={refs.driverEventsRef}
              />
            ))}
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

export default RaceDashboard;
