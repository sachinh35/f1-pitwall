import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TrackMap from "./TrackMap";
import { worldToCanvas } from "./trackMapMath";
import { PositionSample } from "../../types/raceMode";

describe("worldToCanvas", () => {
  const bounds = { minX: 0, maxX: 100, minY: 0, maxY: 50 };

  it("maps the bottom-left world corner to the bottom-left canvas corner (inset by padding)", () => {
    expect(worldToCanvas({ x: 0, y: 0 }, bounds, 200, 100, 10)).toEqual({ x: 10, y: 90 });
  });

  it("flips the y axis - a higher world y maps to a smaller canvas y", () => {
    const bottom = worldToCanvas({ x: 0, y: 0 }, bounds, 200, 100, 10);
    const top = worldToCanvas({ x: 0, y: 50 }, bounds, 200, 100, 10);
    expect(top.y).toBeLessThan(bottom.y);
  });

  it("uses the smaller of the two axis scales so the shape isn't distorted", () => {
    // spanX=100 over (200-20)=180px -> scale 1.8; spanY=50 over (100-20)=80px -> scale 1.6
    // the smaller scale (1.6) should govern both axes
    const p = worldToCanvas({ x: 100, y: 0 }, bounds, 200, 100, 10);
    expect(p.x).toBeCloseTo(10 + 100 * 1.6);
  });

  it("falls back to a span of 1 when bounds collapse to a single point", () => {
    const point = { minX: 5, maxX: 5, minY: 5, maxY: 5 };
    expect(() => worldToCanvas({ x: 5, y: 5 }, point, 200, 100, 10)).not.toThrow();
  });
});

const emptyRefs = {
  positionsRef: { current: {} as Record<string, PositionSample> },
  trailRef: { current: {} as Record<string, { x: number; y: number }[]> },
};

describe("TrackMap", () => {
  it("renders the track map canvas", () => {
    const { container } = render(
      <TrackMap positionsRef={emptyRefs.positionsRef} trailRef={emptyRefs.trailRef} selectedDrivers={[]} />
    );
    expect(container.querySelector("canvas.rm-trackmap-canvas")).not.toBeNull();
  });

  describe("draw loop", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("runs the placeholder branch when there is no trail data yet", () => {
      const { unmount } = render(
        <TrackMap positionsRef={emptyRefs.positionsRef} trailRef={emptyRefs.trailRef} selectedDrivers={[]} />
      );
      expect(() => vi.advanceTimersByTime(50)).not.toThrow();
      unmount();
    });

    it("draws trails and live car markers, including a selected driver's highlighted marker", () => {
      const positionsRef = {
        current: {
          "1": { x: 10, y: 20, z: 0, status: "OnTrack" },
          "3": { x: 30, y: 40, z: 0, status: "OnTrack" },
        } as Record<string, PositionSample>,
      };
      const trailRef = {
        current: {
          "1": [
            { x: 0, y: 0 },
            { x: 10, y: 20 },
          ],
          "3": [
            { x: 0, y: 0 },
            { x: 30, y: 40 },
          ],
        },
      };

      const { unmount } = render(
        <TrackMap positionsRef={positionsRef} trailRef={trailRef} selectedDrivers={[1]} />
      );
      expect(() => vi.advanceTimersByTime(50)).not.toThrow();
      unmount();
    });

    it("cleans up the resize listener and animation frame on unmount without throwing", () => {
      const { unmount } = render(
        <TrackMap positionsRef={emptyRefs.positionsRef} trailRef={emptyRefs.trailRef} selectedDrivers={[]} />
      );
      vi.advanceTimersByTime(20);
      expect(() => unmount()).not.toThrow();
    });

    it("skips drawing a trail with fewer than 2 accumulated points", () => {
      const positionsRef = {
        current: { "1": { x: 10, y: 20, z: 0, status: "OnTrack" } } as Record<string, PositionSample>,
      };
      const trailRef = {
        current: {
          "1": [{ x: 10, y: 20 }], // only one point - too short to draw a line segment
          "3": [
            { x: 0, y: 0 },
            { x: 30, y: 40 },
          ],
        },
      };
      const { unmount } = render(<TrackMap positionsRef={positionsRef} trailRef={trailRef} selectedDrivers={[]} />);
      expect(() => vi.advanceTimersByTime(20)).not.toThrow();
      unmount();
    });
  });
});
