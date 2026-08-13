import React, { useEffect, useMemo, useRef, useState } from "react";
import { getRosterEntry } from "../../data/driverRoster";
import { getLapComparison } from "../../services/api";
import { DriverTiming, LapComparisonData } from "../../types/raceMode";

interface LapDeltaChartProps {
  sessionKey: number | null;
  /** The two drivers selected in the timing tower (same selection TelemetryLab uses). */
  selectedDrivers: number[];
  drivers: Record<string, DriverTiming>;
}

/** A driver's most recently *completed* lap - NumberOfLaps tracks the lap in progress. */
function lastCompletedLap(timing: DriverTiming | undefined): number {
  const current = timing?.NumberOfLaps ?? 1;
  return Math.max(1, current - 1);
}

function drawTraceCanvas(
  canvas: HTMLCanvasElement,
  distanceA: number[],
  seriesA: number[],
  colorA: string,
  distanceB: number[],
  seriesB: number[],
  colorB: string
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = rect.height * devicePixelRatio;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);

  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);

  const allValues = [...seriesA, ...seriesB];
  const allDistance = [...distanceA, ...distanceB];
  if (allValues.length === 0 || allDistance.length === 0) return;

  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const range = maxV - minV || 1;
  const maxDist = Math.max(...allDistance) || 1;

  const toX = (d: number) => (d / maxDist) * w;
  const toY = (v: number) => h - ((v - minV) / range) * h;

  const drawSeries = (distance: number[], values: number[], color: string) => {
    ctx.beginPath();
    distance.forEach((d, i) => {
      const x = toX(d);
      const y = toY(values[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.stroke();
  };

  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = (i / 3) * h;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  drawSeries(distanceA, seriesA, colorA);
  drawSeries(distanceB, seriesB, colorB);
}

function drawDeltaCanvas(canvas: HTMLCanvasElement, data: LapComparisonData): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio;
  canvas.height = rect.height * devicePixelRatio;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);

  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);

  const { distance_m, delta_seconds, corners } = data.delta;
  if (distance_m.length === 0) return;

  const maxDist = Math.max(...distance_m) || 1;
  const maxAbsDelta = Math.max(0.1, ...delta_seconds.map((d) => Math.abs(d)));

  const toX = (d: number) => (d / maxDist) * w;
  const toY = (v: number) => h / 2 - (v / maxAbsDelta) * (h / 2 - 8);

  // zero line
  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  ctx.lineTo(w, h / 2);
  ctx.stroke();

  // corner markers
  ctx.strokeStyle = "rgba(242,165,60,0.35)";
  ctx.lineWidth = 1;
  corners.forEach((corner) => {
    const x = toX(corner.distance_m);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  });

  // delta trace, colored by sign (teal = gaining, red = losing)
  ctx.lineWidth = 1.8;
  for (let i = 1; i < distance_m.length; i++) {
    const x0 = toX(distance_m[i - 1]);
    const y0 = toY(delta_seconds[i - 1]);
    const x1 = toX(distance_m[i]);
    const y1 = toY(delta_seconds[i]);
    ctx.strokeStyle = delta_seconds[i] >= 0 ? "#e6473f" : "#35d6c4";
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }
}

const LapDeltaChart: React.FC<LapDeltaChartProps> = ({ sessionKey, selectedDrivers, drivers }) => {
  const [lapA, setLapA] = useState<number>(1);
  const [lapB, setLapB] = useState<number>(1);
  const [data, setData] = useState<LapComparisonData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const speedCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const accelCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const deltaCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const [driverA, driverB] = selectedDrivers;
  const rosterA = driverA != null ? getRosterEntry(driverA) : null;
  const rosterB = driverB != null ? getRosterEntry(driverB) : null;

  // Default each lap number to that driver's most recently completed lap
  // whenever the selection changes, without overriding a manual edit mid-session.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (driverA != null) setLapA(lastCompletedLap(drivers[String(driverA)]));
    if (driverB != null) setLapB(lastCompletedLap(drivers[String(driverB)]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [driverA, driverB]);

  const canCompare = sessionKey != null && driverA != null && driverB != null && lapA > 0 && lapB > 0;

  const handleCompare = async () => {
    if (!canCompare || driverA == null || driverB == null || sessionKey == null) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getLapComparison(sessionKey, driverA, lapA, driverB, lapB);
      setData(result);
    } catch (err) {
      console.error("Failed to fetch lap comparison", err);
      setError("No data for that lap pairing yet - try a lap that's already completed.");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!data) return;
    if (speedCanvasRef.current) {
      drawTraceCanvas(
        speedCanvasRef.current,
        data.driver_a.distance_m, data.driver_a.speed_kmh, rosterA?.teamColor ?? "#f2a53c",
        data.driver_b.distance_m, data.driver_b.speed_kmh, rosterB?.teamColor ?? "#35d6c4"
      );
    }
    if (accelCanvasRef.current) {
      drawTraceCanvas(
        accelCanvasRef.current,
        data.driver_a.distance_m, data.driver_a.acceleration_ms2, rosterA?.teamColor ?? "#f2a53c",
        data.driver_b.distance_m, data.driver_b.acceleration_ms2, rosterB?.teamColor ?? "#35d6c4"
      );
    }
    if (deltaCanvasRef.current) {
      drawDeltaCanvas(deltaCanvasRef.current, data);
    }
  }, [data, rosterA, rosterB]);

  const summary = useMemo(() => {
    if (!data || data.delta.delta_seconds.length === 0) return null;
    const final = data.delta.delta_seconds[data.delta.delta_seconds.length - 1];
    return final;
  }, [data]);

  if (selectedDrivers.length < 2) {
    return (
      <div style={{ color: "var(--text-faint)", fontSize: 13 }}>
        Select 2 drivers in the timing tower to compare completed laps.
      </div>
    );
  }

  return (
    <div>
      <div className="lap-compare-controls">
        <label>
          <span style={{ color: rosterA?.teamColor }}>{rosterA?.tla}</span> lap
          <input type="number" min={1} value={lapA} onChange={(e) => setLapA(Number(e.target.value))} />
        </label>
        <label>
          <span style={{ color: rosterB?.teamColor }}>{rosterB?.tla}</span> lap
          <input type="number" min={1} value={lapB} onChange={(e) => setLapB(Number(e.target.value))} />
        </label>
        <button className="lap-compare-btn" onClick={handleCompare} disabled={!canCompare || loading}>
          {loading ? "Comparing…" : "Compare"}
        </button>
      </div>

      {error && <div style={{ color: "var(--flag-red, #e6473f)", fontSize: 12.5, marginTop: 8 }}>{error}</div>}

      {data && (
        <div style={{ marginTop: 12 }}>
          {summary != null && (
            <div style={{ fontSize: 12.5, color: "var(--text-lo)", marginBottom: 8 }}>
              Over the lap, <b style={{ color: rosterB?.teamColor }}>{rosterB?.tla}</b>{" "}
              {summary >= 0 ? "lost" : "gained"} <span className="mono">{Math.abs(summary).toFixed(3)}s</span> relative
              to <b style={{ color: rosterA?.teamColor }}>{rosterA?.tla}</b>, across {data.delta.corners.length} detected corners.
            </div>
          )}

          <div className="rm-panel-label" style={{ marginTop: 4 }}>Speed vs. Distance</div>
          <canvas ref={speedCanvasRef} className="rm-telemetry-canvas" />

          <div className="rm-panel-label" style={{ marginTop: 10 }}>Acceleration vs. Distance (m/s²)</div>
          <canvas ref={accelCanvasRef} className="rm-telemetry-canvas" />

          <div className="rm-panel-label" style={{ marginTop: 10 }}>
            Time Delta vs. Distance <span style={{ fontWeight: 400, color: "var(--text-faint)" }}>(amber lines = detected corners)</span>
          </div>
          <canvas ref={deltaCanvasRef} className="rm-telemetry-canvas" />

          <div className="rm-telemetry-legend">
            <span><i style={{ background: rosterA?.teamColor }} />{rosterA?.tla} (lap {data.driver_a.lap_number})</span>
            <span><i style={{ background: rosterB?.teamColor }} />{rosterB?.tla} (lap {data.driver_b.lap_number})</span>
            <span><i style={{ background: "#e6473f" }} />Losing time</span>
            <span><i style={{ background: "#35d6c4" }} />Gaining time</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default LapDeltaChart;
