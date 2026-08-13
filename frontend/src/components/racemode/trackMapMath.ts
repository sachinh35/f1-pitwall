export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/**
 * Pure coordinate-transform: maps a world-space (F1 Position.z) point into
 * canvas pixel space, given the accumulated trail bounds and canvas size.
 * Kept side-effect free so it can be unit tested directly rather than by
 * pixel-diffing canvas output - same pattern as TelemetryLab's scaleToBand.
 * Y is flipped (canvas grows downward, track telemetry grows upward).
 *
 * Split into its own module (rather than living alongside the component) purely so
 * TrackMap.tsx can export only the component itself, which Vite's Fast Refresh requires
 * for hot-reloading to work on that file (see eslint's react-refresh/only-export-components).
 */
export function worldToCanvas(
  point: { x: number; y: number },
  bounds: Bounds,
  width: number,
  height: number,
  padding: number
): { x: number; y: number } {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  return {
    x: padding + (point.x - bounds.minX) * scale,
    y: height - padding - (point.y - bounds.minY) * scale,
  };
}
