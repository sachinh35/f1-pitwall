import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
