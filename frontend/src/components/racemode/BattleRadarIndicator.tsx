import React, { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { getRosterEntry } from "../../data/driverRoster";
import { BattleRadarAlert } from "../../types/raceMode";

interface BattleRadarIndicatorProps {
  alert: BattleRadarAlert | undefined;
}

const BattleRadarIndicator: React.FC<BattleRadarIndicatorProps> = ({ alert }) => {
  const [open, setOpen] = useState(false);

  if (!alert) return null;

  const aheadRoster = alert.ahead_driver_number != null ? getRosterEntry(alert.ahead_driver_number) : null;
  const chartData = alert.lap_history.map((point) => ({
    lap: point.lap_number,
    gap: point.gap_seconds,
  }));

  return (
    <span
      className={`battle-radar-badge battle-radar-${alert.alert_level}`}
      tabIndex={0}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      title={alert.alert_level === "battle" ? "Battle imminent" : "Battle forming"}
    >
      {alert.alert_level === "battle" ? "▲" : "△"}
      {open && (
        <span className="battle-radar-popover">
          {aheadRoster && <span className="battle-radar-popover-head">Closing on {aheadRoster.tla}</span>}
          <span className="battle-radar-popover-gap">{alert.gap_seconds.toFixed(2)}s</span>
          <LineChart width={170} height={90} data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
            <XAxis dataKey="lap" tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} width={30} />
            <Tooltip
              contentStyle={{ background: "var(--panel-900)", border: "1px solid var(--line-800)", fontSize: 10 }}
              labelFormatter={(lap) => `Lap ${lap}`}
              formatter={(value: number) => [`${value.toFixed(2)}s`, "Gap"]}
            />
            <Line
              type="monotone"
              dataKey="gap"
              stroke={alert.alert_level === "battle" ? "var(--flag-red)" : "var(--amber)"}
              strokeWidth={2}
              dot={{ r: 2 }}
            />
          </LineChart>
        </span>
      )}
    </span>
  );
};

export default BattleRadarIndicator;
