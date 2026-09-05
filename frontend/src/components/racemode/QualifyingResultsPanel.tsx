import React from "react";
import { QualifyingResultEntry } from "../../services/api";
import { getRosterEntry } from "../../data/driverRoster";
import { formatLapDuration } from "../../utils/formatting";

interface QualifyingResultsPanelProps {
  /** Keyed by segment ("Q1"/"Q2"/"Q3") - a segment absent here just hasn't ended yet. */
  results: Record<string, QualifyingResultEntry[]>;
}

const PARTS_IN_ORDER = ["Q1", "Q2", "Q3"];

/**
 * One collapsed-by-default <details> card per completed qualifying segment - collapsed
 * so the still-running segment's Timing Tower stays the focus, but each finished
 * segment's final order/times/eliminations stay one click away instead of disappearing
 * the moment the next segment resets the live timing state.
 */
const QualifyingResultsPanel: React.FC<QualifyingResultsPanelProps> = ({ results }) => {
  const completedParts = PARTS_IN_ORDER.filter((part) => (results[part]?.length ?? 0) > 0);
  if (completedParts.length === 0) return null;

  return (
    <div className="rm-qualifying-results">
      {completedParts.map((part) => {
        const entries = [...results[part]].sort((a, b) => (a.position ?? 99) - (b.position ?? 99));
        return (
          <details key={part} className="rm-qr-card">
            <summary className="rm-qr-summary">
              <span>{part} Results</span>
              <span className="rm-qr-count">{entries.length} drivers</span>
            </summary>
            <table className="rm-qr-table">
              <thead>
                <tr>
                  <th>Pos</th>
                  <th>Driver</th>
                  <th>Best Lap</th>
                  <th>Gap</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => {
                  const roster = getRosterEntry(entry.driver_number);
                  return (
                    <tr key={entry.driver_number} className={entry.eliminated ? "eliminated" : undefined}>
                      <td className="mono">{entry.position ?? "-"}</td>
                      <td>
                        <span className="rm-qr-swatch" style={{ background: roster.teamColor }} />
                        {roster.tla}
                      </td>
                      <td className="mono">
                        {entry.best_lap_seconds != null ? formatLapDuration(entry.best_lap_seconds) : "-"}
                      </td>
                      <td className="mono">
                        {entry.gap_to_leader_seconds == null
                          ? "-"
                          : entry.gap_to_leader_seconds === 0
                            ? "Leader"
                            : `+${entry.gap_to_leader_seconds.toFixed(3)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        );
      })}
    </div>
  );
};

export default QualifyingResultsPanel;
