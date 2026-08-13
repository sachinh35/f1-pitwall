import { LapMetricPoint, tukeyFences } from "../../utils/compareMetrics";

/**
 * Pure, side-effect-free coordinate-transform helpers for CompareWidget.tsx's canvas drawing -
 * split into their own module (rather than living alongside the component) purely so that
 * file can export only the CompareWidget component itself, which Vite's Fast Refresh requires
 * for hot-reloading to work on that file (see eslint's react-refresh/only-export-components).
 */

/**
 * Pure coordinate-transform: maps a data value within [0, domainMax] to a canvas y pixel
 * coordinate confined to a band, with the band's own top-left origin as (bandTop, value=0)
 * baseline. Kept side-effect free (no canvas/DOM access) so it can be unit tested directly
 * rather than by pixel-diffing canvas output - carried over from the old TelemetryLab
 * (single-metric widgets now always use bandTop=0/bandHeight=canvas height, but the
 * band-relative signature is kept in case a future widget stacks more than one band).
 */
export function scaleToBand(value: number, domainMax: number, bandTop: number, bandHeight: number): number {
  return bandTop + bandHeight - (value / domainMax) * bandHeight;
}

export interface LapValueBounds {
  minLap: number;
  maxLap: number;
  minValue: number;
  maxValue: number;
}

/**
 * Pure coordinate-transform: maps a { lap, value } point into canvas pixel space, given the
 * lap/value bounds actually observed across the selected drivers' histories for a discrete
 * metric. Kept side-effect free so it can be unit tested directly - same pattern as
 * scaleToBand above and TrackMap.worldToCanvas. X grows with lap number (left->right); Y is
 * flipped so a larger value sits higher on the canvas (canvas y grows downward).
 */
export function lapPointToCanvas(
  lap: number,
  value: number,
  bounds: LapValueBounds,
  width: number,
  height: number,
  padding: number
): { x: number; y: number } {
  const spanLap = bounds.maxLap - bounds.minLap || 1;
  const spanValue = bounds.maxValue - bounds.minValue || 1;
  return {
    x: padding + ((lap - bounds.minLap) / spanLap) * (width - padding * 2),
    y: height - padding - ((value - bounds.minValue) / spanValue) * (height - padding * 2),
  };
}

/**
 * Pure: the position a lap-metric point should actually render at, clamped to whichever edge
 * of `bounds` its value falls outside of (e.g. a pit stop, a Safety Car lap, or any other
 * statistical outlier excluded from the scaling calculation - see computeLapValueBounds)
 * rather than plotted off-canvas or dragging the axis out to fit it. `isOffScale` tells the
 * caller to style this point distinctly (muted/dashed) instead of like a genuine value at that
 * height.
 */
export function clampedLapPointToCanvas(
  point: LapMetricPoint,
  bounds: LapValueBounds,
  width: number,
  height: number,
  padding: number
): { x: number; y: number; isOffScale: boolean } {
  const isAboveScale = point.value > bounds.maxValue;
  const isBelowScale = point.value < bounds.minValue;
  const clampedValue = isAboveScale ? bounds.maxValue : isBelowScale ? bounds.minValue : point.value;
  const { x, y } = lapPointToCanvas(point.lap, clampedValue, bounds, width, height, padding);
  return { x, y, isOffScale: isAboveScale || isBelowScale };
}

/**
 * Pure: scans the selected drivers' combined lap history for a discrete metric and returns
 * the lap/value bounds actually observed, or null if no driver has any points yet. Extracted
 * out of the draw loop (was previously computed inline there) so both the draw loop and the
 * DOM event-marker overlay effect below can share exactly one bounds calculation instead of
 * two copies drifting apart - same rationale as scaleToBand/lapPointToCanvas.
 *
 * Excludes each driver's own statistical outliers (see tukeyFences) from the *value* range
 * only (never the lap range - an outlier lap is still a perfectly normal lap number to plot on
 * the X axis) before computing min/max. A pit stop (or a Safety Car lap, or any other one-off
 * slowdown) routinely spikes that one lap's sector/lap time well above normal racing pace;
 * without this, that single outlier lap would drag the whole Y-axis scale out to fit it and
 * flatten every other driver's detail down to a thin band. Excluded points are still plotted
 * (see clampedLapPointToCanvas above), just clamped to the resulting tighter scale instead of
 * stretching it. Falls back to including every point if excluding outliers would leave no data
 * to scale from at all (e.g. a driver whose only laps so far are all outliers).
 */
export function computeLapValueBounds(
  perDriverHistory: Record<number, LapMetricPoint[]>,
  drivers: number[]
): LapValueBounds | null {
  let minLap = Infinity;
  let maxLap = -Infinity;
  let minValue = Infinity;
  let maxValue = -Infinity;
  let anyPoints = false;
  let anyScalingPoints = false;

  for (const driverNumber of drivers) {
    const points = perDriverHistory[driverNumber];
    if (!points || points.length === 0) continue;
    anyPoints = true;
    const fences = tukeyFences(points.map((p) => p.value));
    for (const p of points) {
      if (p.lap < minLap) minLap = p.lap;
      if (p.lap > maxLap) maxLap = p.lap;
      const isOutlier = fences !== null && (p.value < fences.lower || p.value > fences.upper);
      if (isOutlier) continue;
      anyScalingPoints = true;
      if (p.value < minValue) minValue = p.value;
      if (p.value > maxValue) maxValue = p.value;
    }
  }

  if (!anyPoints) return null;

  // Nothing but outliers to go on (yet) - fall back to scaling from every point rather than
  // returning a broken (Infinity-bounded) range.
  /* v8 ignore start -- mathematically unreachable: tukeyFences() only returns non-null when
   * iqr > 0, in which case Q1/Q3 (derived from these same points) always lie within
   * [lower, upper] by construction, so at least one point can never be classified an outlier. */
  if (!anyScalingPoints) {
    for (const driverNumber of drivers) {
      const points = perDriverHistory[driverNumber];
      if (!points) continue;
      for (const p of points) {
        if (p.value < minValue) minValue = p.value;
        if (p.value > maxValue) maxValue = p.value;
      }
    }
    /* v8 ignore stop */
  }

  const valueSpan = maxValue - minValue || 1;
  const valuePad = valueSpan * 0.05;
  return {
    minLap,
    maxLap,
    minValue: minValue - valuePad,
    maxValue: maxValue + valuePad,
  };
}

/**
 * Pure: how many laps to skip between X-axis lap-number labels, so a wide lap range (e.g. a
 * 60-lap race) doesn't try to stamp a number at every single lap and overlap them all.
 * Every lap is labeled up to a span of 12; beyond that the step grows just enough to keep
 * roughly 12 labels on screen.
 */
export function lapLabelStep(spanLaps: number): number {
  if (spanLaps <= 12) return 1;
  return Math.ceil(spanLaps / 12);
}

/**
 * Pure: given a driver's parallel lap-tag array (one entry per buffered continuous telemetry
 * sample - see lapTagRef in CompareWidget.tsx), returns the indices where the tag changes to a
 * new known lap, i.e. a lap-completion boundary crossing. Entries equal to `unknownSentinel`
 * (no TimingData has arrived yet for this driver) are skipped entirely rather than treated as
 * a "change" - both when they lead the array (before the first known lap arrives) and when
 * they trail it, and skipping never itself counts as crossing a boundary.
 */
export function detectLapBoundaryIndices(lapTags: number[], unknownSentinel: number): number[] {
  const indices: number[] = [];
  let previousKnown: number | undefined;

  for (let i = 0; i < lapTags.length; i++) {
    const tag = lapTags[i];
    if (tag === unknownSentinel) continue;
    if (previousKnown !== undefined && tag !== previousKnown) {
      indices.push(i);
    }
    previousKnown = tag;
  }

  return indices;
}

/**
 * Pure: finds the index in a driver's lap-tag array whose tagged lap is closest to `lap`,
 * within `tolerance` laps - used to map a DriverEventMarker (which only knows the lap it
 * happened on) onto the continuous rolling-window x-axis (which only knows sample index).
 * Returns null if no tagged sample is within tolerance, which is deliberate: an event whose
 * lap has scrolled out of the current MAX_HISTORY window should simply not render, rather
 * than being clamped onto whichever edge sample happens to be closest.
 */
export function findLapTagIndex(
  lapTags: number[],
  lap: number,
  unknownSentinel: number,
  tolerance = 1
): number | null {
  let bestIndex: number | null = null;
  let bestDiff = Infinity;

  for (let i = 0; i < lapTags.length; i++) {
    const tag = lapTags[i];
    if (tag === unknownSentinel) continue;
    const diff = Math.abs(tag - lap);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIndex = i;
    }
  }

  if (bestIndex === null || bestDiff > tolerance) return null;
  return bestIndex;
}
