import { describe, expect, it } from "vitest";
import { DRIVER_COLORS, getDriverColor } from "./chartColors";

describe("getDriverColor", () => {
  it("returns the color at the given index", () => {
    expect(getDriverColor(1, 0)).toBe(DRIVER_COLORS[0]);
    expect(getDriverColor(1, 2)).toBe(DRIVER_COLORS[2]);
  });

  it("cycles through colors via modulo once index exceeds the palette length", () => {
    expect(getDriverColor(1, DRIVER_COLORS.length)).toBe(DRIVER_COLORS[0]);
    expect(getDriverColor(1, DRIVER_COLORS.length + 3)).toBe(DRIVER_COLORS[3]);
  });
});
