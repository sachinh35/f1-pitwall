import React, { useEffect, useRef, useState } from "react";
import { getRosterEntry } from "../../data/driverRoster";
import { TelemetrySample } from "../../types/raceMode";
import {
  COMPARE_METRIC_LABELS,
  COMPARE_METRICS,
  CompareMetric,
  DiscreteCompareMetric,
  DriverEventMarker,
  LapMetricPoint,
  formatMetricValue,
  isDiscreteMetric,
} from "../../utils/compareMetrics";
import {
  clampedLapPointToCanvas,
  computeLapValueBounds,
  detectLapBoundaryIndices,
  findLapTagIndex,
  LapValueBounds,
  lapLabelStep,
  lapPointToCanvas,
  scaleToBand,
} from "./compareWidgetMath";

interface CompareWidgetProps {
  metric: CompareMetric;
  onMetricChange: (metric: CompareMetric) => void;
  onRemove: () => void;
  /** Up to 4 drivers, selected by clicking rows in the timing tower - shared across every
   * comparison widget, not a per-widget picker. */
  selectedDrivers: number[];
  /** A ref, not React state - see TrackMap.tsx for why. */
  telemetryRef: React.MutableRefObject<Record<string, TelemetrySample>>;
  /** A ref, not React state - accumulated once per lap (or per sector) per driver in
   * RaceMode.tsx's TimingData handler, can update many times per second across ~20 drivers
   * during a fast replay. */
  lapMetricHistoryRef: React.MutableRefObject<Record<DiscreteCompareMetric, Record<number, LapMetricPoint[]>>>;
  /** Each driver's latest known NumberOfLaps - telemetry samples carry no lap number of
   * their own, so this is how the continuous (speed/throttle/brake) charts below tag each
   * buffered sample with the lap it was captured on, to draw lap-completion markers on an
   * axis that otherwise has no notion of laps at all. */
  currentLapRef: React.MutableRefObject<Record<number, number>>;
  /** A ref, not React state - pit stops/tyre changes/penalties accumulated across the whole
   * session per driver in RaceMode.tsx (TimingData/TimingAppData/RaceControlMessages
   * handlers), same ref-not-state reasoning as everything else here. Rendered as small
   * hoverable markers over both continuous and discrete charts below. */
  driverEventsRef: React.MutableRefObject<Record<number, DriverEventMarker[]>>;
}

type ContinuousCompareMetric = "speed" | "throttle" | "brake";

const MAX_HISTORY = 300;
const BAND_LABEL_COLOR = "#5b6472";
const GRIDLINE_STYLE = "rgba(255,255,255,0.06)";
const PLACEHOLDER_COLOR = "#5b6472";
// Shared plotting inset for discrete (lap-indexed) charts - lifted to module scope so
// drawDiscreteSeries, drawDiscreteLapGridlines and buildDiscreteEventMarkers all agree on
// exactly the same plotting area rather than re-declaring the literal in three places.
const DISCRETE_PADDING = 14;
// Sentinel lap-tag value for a continuous telemetry sample captured before any TimingData
// message has told us this driver's current lap yet (see lapTagRef below).
const UNKNOWN_LAP_TAG = -1;
// How often (ms) the event-marker DOM overlay is recomputed - these change at most once per
// lap/pit stop/penalty, far slower than the 60fps draw loop, so a slow poll is plenty and
// avoids re-rendering DOM elements every animation frame for something this infrequent.
const MARKER_REFRESH_INTERVAL_MS = 300;

function continuousValue(sample: TelemetrySample, metric: ContinuousCompareMetric): number {
  switch (metric) {
    case "speed":
      return sample.speed_kmh;
    case "throttle":
      return sample.throttle_pct;
    case "brake":
      return sample.brake_pct;
  }
}

/** Foreground tint per tyre compound, matching the existing tyre-chip-mini/tyre-stint-segment
 * palette (see raceMode.css) - reused here so a tyre-change marker's dot reads as "the tyre
 * that went on" rather than an arbitrary flat color. */
const COMPOUND_MARKER_COLOR: Record<string, string> = {
  soft: "#ff6b6b",
  medium: "#f2c94c",
  hard: "#e7ebf1",
  intermediate: "#52e252",
  wet: "#64c4ff",
};
// Penalties are the one event kind that's arguably "alert-like" rather than routine, so they
// get a shared warning tint instead of each driver's own (already busy) line color.
const PENALTY_MARKER_COLOR = "#f2a53c";

function glyphForEventKind(kind: DriverEventMarker["kind"]): string {
  switch (kind) {
    case "pit":
      return "P";
    case "tyre":
      return "●";
    case "penalty":
      return "!";
  }
}

function colorForEvent(event: DriverEventMarker, driverColor: string): string {
  if (event.kind === "penalty") return PENALTY_MARKER_COLOR;
  if (event.kind === "tyre" && event.compound && COMPOUND_MARKER_COLOR[event.compound]) {
    return COMPOUND_MARKER_COLOR[event.compound];
  }
  return driverColor;
}

/** Rendered as an invisible-until-hovered DOM marker over the canvas - see the
 * `.rm-event-marker` CSS (opacity 0 by default, revealed on :hover) and the effect below.
 * Covers two cases: a plain data point (isEvent=false, one per driver per lap on a discrete
 * chart, showing that lap's value on hover) and a pit/tyre/penalty event (isEvent=true,
 * distinct glyph/color, shown on both chart types). A point that's both (a lap with a value
 * AND an event) is just one marker using the event's glyph, with both pieces of information
 * combined into `title`. */
interface RenderedMarker {
  key: string;
  x: number;
  y: number;
  color: string;
  glyph: string;
  title: string;
  isEvent: boolean;
  /** Only meaningful when isEvent is true - used for a minor per-kind CSS tweak. */
  kind?: DriverEventMarker["kind"];
}

const CompareWidget: React.FC<CompareWidgetProps> = ({
  metric,
  onMetricChange,
  onRemove,
  selectedDrivers,
  telemetryRef,
  lapMetricHistoryRef,
  currentLapRef,
  driverEventsRef,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Continuous-metric rolling history/dedup state - reset whenever `metric` changes, since
  // a history array built up for e.g. "speed" is meaningless once the widget is switched to
  // "throttle".
  const historyRef = useRef<Record<number, number[]>>({});
  const lastSeenRef = useRef<Record<number, TelemetrySample | undefined>>({});
  // Parallel to historyRef (same index space, shifted in lockstep) - tags each buffered
  // continuous sample with the lap it was captured on, per Task 1's lap-completion-marker
  // requirement. See detectLapBoundaryIndices/findLapTagIndex above.
  const lapTagRef = useRef<Record<number, number[]>>({});
  // Hoverable marker overlay (per-lap data points on discrete charts, plus pit/tyre/penalty
  // events on both chart types) - plain React state, not a ref: these change far too
  // infrequently to justify canvas-only rendering, and need to be real DOM elements so they
  // can carry a native `title` tooltip (canvas pixels can't be hovered). Invisible by default,
  // revealed on hover only (see the `.rm-event-marker` CSS) - see the effect below and the
  // JSX render at the bottom of this component.
  const [eventMarkers, setEventMarkers] = useState<RenderedMarker[]>([]);

  useEffect(() => {
    historyRef.current = {};
    lastSeenRef.current = {};
    lapTagRef.current = {};

    const canvas = canvasRef.current;
    /* v8 ignore next -- canvasRef is always set once this effect runs post-mount; defensive only */
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    /* v8 ignore next -- jsdom's canvas mock (see setupTests.ts) always returns a 2d context; defensive only */
    if (!ctx) return;

    let rafId: number;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * devicePixelRatio;
      canvas.height = rect.height * devicePixelRatio;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const drivers = selectedDrivers.slice(0, 4);
    const discrete = isDiscreteMetric(metric);
    const label = COMPARE_METRIC_LABELS[metric];

    const drawGridlines = (w: number, h: number) => {
      ctx.strokeStyle = GRIDLINE_STYLE;
      ctx.lineWidth = 1;
      for (let i = 0; i <= 2; i++) {
        const y = (i / 2) * h;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
    };

    const drawLabel = () => {
      ctx.fillStyle = BAND_LABEL_COLOR;
      ctx.font = "10px -apple-system, sans-serif";
      ctx.fillText(label.toUpperCase(), 4, 11);
    };

    const drawPlaceholder = (text: string, h: number) => {
      ctx.fillStyle = PLACEHOLDER_COLOR;
      ctx.font = "13px -apple-system, sans-serif";
      ctx.fillText(text, 12, h / 2 + 4);
    };

    const drawContinuousSeries = (values: number[], color: string, w: number, h: number, domainMax: number) => {
      if (values.length < 2) return;

      ctx.beginPath();
      values.forEach((value, i) => {
        const x = (i / (MAX_HISTORY - 1)) * w;
        const y = scaleToBand(value, domainMax, 0, h);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.6;
      ctx.stroke();

      // emphasize the endpoint
      const lastValue = values[values.length - 1];
      const ly = scaleToBand(lastValue, domainMax, 0, h);
      ctx.beginPath();
      ctx.arc(w - 3, ly, 3, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    };

    // Task 1 (continuous): a short, unobtrusive tick at the bottom edge for each lap
    // boundary crossed within the current rolling window - deliberately not a full-height
    // line so up to 4 overlapping drivers' ticks don't obscure the trace lines above them.
    const drawLapBoundaryTicks = (lapTags: number[], color: string, w: number, h: number, labeledLaps: Set<number>) => {
      const indices = detectLapBoundaryIndices(lapTags, UNKNOWN_LAP_TAG);
      if (indices.length === 0) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.6;
      indices.forEach((i) => {
        const x = (i / (MAX_HISTORY - 1)) * w;
        ctx.beginPath();
        ctx.moveTo(x, h);
        ctx.lineTo(x, h - 6);
        ctx.stroke();
      });
      ctx.restore();

      // Label each lap number once (not once per driver) - multiple drivers crossing a lap
      // boundary within the same rolling window would otherwise stamp the same number on
      // top of itself repeatedly.
      ctx.save();
      ctx.fillStyle = BAND_LABEL_COLOR;
      ctx.font = "9px ui-monospace, monospace";
      ctx.textAlign = "center";
      indices.forEach((i) => {
        const lap = lapTags[i];
        if (labeledLaps.has(lap)) return;
        labeledLaps.add(lap);
        const x = (i / (MAX_HISTORY - 1)) * w;
        ctx.fillText(String(lap), x, h - 9);
      });
      ctx.restore();
    };

    const drawDiscreteSeries = (points: LapMetricPoint[], color: string, w: number, h: number, bounds: LapValueBounds) => {
      if (points.length === 0) return;

      const plotted = points.map((p) => clampedLapPointToCanvas(p, bounds, w, h, DISCRETE_PADDING));

      // Segments touching an off-scale (pit-affected) point are drawn muted/dashed rather
      // than full-color - otherwise the line still shoots up to the clamped value at full
      // opacity, recreating the same visual spike the axis-scale exclusion above was meant
      // to avoid, just at a fixed height instead of dragging the whole chart out.
      for (let i = 1; i < plotted.length; i++) {
        const prev = plotted[i - 1];
        const curr = plotted[i];
        const muted = prev.isOffScale || curr.isOffScale;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(curr.x, curr.y);
        if (muted) {
          ctx.globalAlpha = 0.35;
          ctx.setLineDash([3, 3]);
          ctx.lineWidth = 1.2;
        } else {
          ctx.lineWidth = 1.6;
        }
        ctx.strokeStyle = color;
        ctx.stroke();
        ctx.restore();
      }

      // Off-scale points (pit in/out laps excluded from the axis scale, see
      // computeLapValueBounds) get a muted, dashed hollow marker pinned at the clamped
      // position instead of a solid dot - still visibly "something happened here", without
      // reading as a genuine value at that height.
      plotted.forEach(({ x, y, isOffScale }) => {
        if (!isOffScale) return;
        ctx.save();
        ctx.globalAlpha = 0.45;
        ctx.setLineDash([2, 2]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      });

      // Emphasize the most recent point, same convention as drawContinuousSeries above -
      // unless it's off-scale, where the muted marker above already covers it.
      const last = plotted[plotted.length - 1];
      if (!last.isOffScale) {
        ctx.beginPath();
        ctx.arc(last.x, last.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }
    };

    // Task 1 (discrete): a light vertical gridline at each integer lap within the currently
    // computed bounds, independent of which driver contributed which point.
    const drawDiscreteLapGridlines = (bounds: LapValueBounds, w: number, h: number) => {
      const start = Math.ceil(bounds.minLap);
      const end = Math.floor(bounds.maxLap);

      ctx.save();
      ctx.strokeStyle = GRIDLINE_STYLE;
      ctx.lineWidth = 1;
      for (let lap = start; lap <= end; lap++) {
        const { x } = lapPointToCanvas(lap, bounds.minValue, bounds, w, h, DISCRETE_PADDING);
        ctx.beginPath();
        ctx.moveTo(x, DISCRETE_PADDING);
        ctx.lineTo(x, h - DISCRETE_PADDING);
        ctx.stroke();
      }
      ctx.restore();

      // Thinned out on a long lap range so labels don't overlap (e.g. a 60-lap race
      // shouldn't try to stamp 60 numbers across one widget's width).
      ctx.save();
      ctx.fillStyle = BAND_LABEL_COLOR;
      ctx.font = "9px ui-monospace, monospace";
      ctx.textAlign = "center";
      const step = lapLabelStep(end - start);
      for (let lap = start; lap <= end; lap += step) {
        const { x } = lapPointToCanvas(lap, bounds.minValue, bounds, w, h, DISCRETE_PADDING);
        ctx.fillText(String(lap), x, h - 2);
      }
      ctx.restore();
    };

    const draw = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      drawGridlines(w, h);
      drawLabel();

      if (drivers.length === 0) {
        drawPlaceholder(`Select up to 4 drivers in the timing tower to compare ${label}`, h);
      } else if (discrete) {
        const discreteMetric = metric as DiscreteCompareMetric;
        const perDriverHistory = lapMetricHistoryRef.current[discreteMetric];
        const bounds = computeLapValueBounds(perDriverHistory, drivers);

        if (!bounds) {
          drawPlaceholder("Waiting for lap data…", h);
        } else {
          drawDiscreteLapGridlines(bounds, w, h);

          drivers.forEach((driverNumber) => {
            const points = perDriverHistory[driverNumber];
            if (!points || points.length === 0) return;
            const roster = getRosterEntry(driverNumber);
            drawDiscreteSeries(points, roster.teamColor, w, h, bounds);
          });
        }
      } else {
        const continuousMetric = metric as ContinuousCompareMetric;

        for (const driverNumber of drivers) {
          const sample = telemetryRef.current[String(driverNumber)];
          if (sample && sample !== lastSeenRef.current[driverNumber]) {
            lastSeenRef.current[driverNumber] = sample;
            const history = historyRef.current[driverNumber] ?? (historyRef.current[driverNumber] = []);
            const lapTags = lapTagRef.current[driverNumber] ?? (lapTagRef.current[driverNumber] = []);
            history.push(continuousValue(sample, continuousMetric));
            lapTags.push(currentLapRef.current[driverNumber] ?? UNKNOWN_LAP_TAG);
            if (history.length > MAX_HISTORY) history.shift();
            if (lapTags.length > MAX_HISTORY) lapTags.shift();
          }
        }

        const labeledLaps = new Set<number>();
        drivers.forEach((driverNumber) => {
          const history = historyRef.current[driverNumber];
          if (!history || history.length === 0) return;
          const roster = getRosterEntry(driverNumber);
          // Speed keeps this driver's own rolling max as the domain - preserves the
          // existing, already-understood normalization behavior from TelemetryLab.
          // Throttle/brake are percentages, directly comparable across drivers - use a
          // fixed 0-100 domain rather than per-driver max.
          const domainMax = continuousMetric === "speed" ? Math.max(...history, 1) : 100;
          drawContinuousSeries(history, roster.teamColor, w, h, domainMax);

          const lapTags = lapTagRef.current[driverNumber];
          if (lapTags) drawLapBoundaryTicks(lapTags, roster.teamColor, w, h, labeledLaps);
        });
      }

      rafId = requestAnimationFrame(draw);
    };
    rafId = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
    };
  }, [telemetryRef, lapMetricHistoryRef, currentLapRef, selectedDrivers, metric]);

  // Task 2: event-marker DOM overlay (pit/tyre/penalty). Deliberately a *separate* effect
  // from the canvas draw loop above rather than folded into it: it only needs the canvas
  // element's CSS size (not a 2D drawing context) to compute marker positions, and it drives
  // React state (real DOM elements, so they can carry a hoverable `title`), which the ctx-
  // gated rAF loop above intentionally never touches. Polls at a slow, fixed interval (see
  // MARKER_REFRESH_INTERVAL_MS) since events change far less often than telemetry.
  useEffect(() => {
    const canvas = canvasRef.current;
    /* v8 ignore next -- canvasRef is always set once this effect runs post-mount; defensive only */
    if (!canvas) return;

    const drivers = selectedDrivers.slice(0, 4);
    const discrete = isDiscreteMetric(metric);

    const computeMarkers = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const markers: RenderedMarker[] = [];

      if (discrete) {
        const discreteMetric = metric as DiscreteCompareMetric;
        const perDriverHistory = lapMetricHistoryRef.current[discreteMetric];
        const bounds = computeLapValueBounds(perDriverHistory, drivers);
        if (bounds) {
          drivers.forEach((driverNumber) => {
            const points = perDriverHistory[driverNumber];
            if (!points || points.length === 0) return;
            const roster = getRosterEntry(driverNumber);
            const events = driverEventsRef.current[driverNumber] ?? [];

            // One hoverable marker per plotted point - default state shows nothing (see
            // .rm-event-marker's CSS), hover reveals this lap's value and, if one happened
            // here, the pit/tyre/penalty event too (matched by exact lap number).
            points.forEach((point) => {
              const { x, y, isOffScale } = clampedLapPointToCanvas(point, bounds, w, h, DISCRETE_PADDING);
              const event = events.find((e) => e.lap === point.lap);
              let valueText = `${roster.tla} · Lap ${point.lap}: ${formatMetricValue(discreteMetric, point.value)}`;
              if (isOffScale) valueText += " (off scale - not counted in the axis range)";

              markers.push({
                key: `${driverNumber}-${point.lap}`,
                x,
                y,
                color: event ? colorForEvent(event, roster.teamColor) : roster.teamColor,
                glyph: event ? glyphForEventKind(event.kind) : "●",
                title: event ? `${valueText}\n${event.label}` : valueText,
                isEvent: Boolean(event),
                kind: event?.kind,
              });
            });
          });
        }
      } else {
        drivers.forEach((driverNumber) => {
          const events = driverEventsRef.current[driverNumber];
          const lapTags = lapTagRef.current[driverNumber];
          if (!events || events.length === 0 || !lapTags || lapTags.length === 0) return;
          const roster = getRosterEntry(driverNumber);
          events.forEach((event, idx) => {
            const index = findLapTagIndex(lapTags, event.lap, UNKNOWN_LAP_TAG);
            if (index === null) return;
            const x = (index / (MAX_HISTORY - 1)) * w;
            markers.push({
              key: `${driverNumber}-${event.kind}-${event.lap}-${idx}`,
              x,
              y: h - 14,
              color: colorForEvent(event, roster.teamColor),
              glyph: glyphForEventKind(event.kind),
              title: event.label,
              isEvent: true,
              kind: event.kind,
            });
          });
        });
      }

      setEventMarkers(markers);
    };

    computeMarkers();
    const intervalId = window.setInterval(computeMarkers, MARKER_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [selectedDrivers, metric, lapMetricHistoryRef, driverEventsRef]);

  return (
    <div className="compare-widget">
      <div className="compare-widget-header">
        <select
          className="compare-widget-select"
          value={metric}
          onChange={(e) => onMetricChange(e.target.value as CompareMetric)}
          aria-label="Comparison metric"
        >
          {COMPARE_METRICS.map((m) => (
            <option key={m} value={m}>
              {COMPARE_METRIC_LABELS[m]}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="compare-widget-remove"
          title="Remove this comparison widget"
          aria-label="Remove this comparison widget"
          onClick={onRemove}
        >
          ×
        </button>
      </div>
      <div className="rm-compare-canvas-wrap">
        <canvas ref={canvasRef} className="rm-compare-canvas" />
        {eventMarkers.map((m) => (
          <span
            key={m.key}
            tabIndex={0}
            className={`rm-event-marker${m.isEvent ? ` rm-event-marker-event rm-event-marker-${m.kind}` : ""}`}
            style={{ left: m.x, top: m.y, color: m.color }}
            title={m.title}
            aria-label={m.title}
          >
            {m.glyph}
          </span>
        ))}
      </div>
      <div className="rm-telemetry-legend">
        {selectedDrivers.slice(0, 4).map((driverNumber) => {
          const roster = getRosterEntry(driverNumber);
          return (
            <span key={driverNumber}>
              <i style={{ background: roster.teamColor }} />
              {roster.tla}
            </span>
          );
        })}
      </div>
    </div>
  );
};

export default CompareWidget;
