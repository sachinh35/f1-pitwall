import { describe, expect, it } from "vitest";
import { getCompoundBadgeStyle, getCompoundColor, getCompoundIconUrl, getCompoundInitial } from "./compoundColors";

describe("getCompoundColor", () => {
  it.each([
    ["SOFT", "#EA3C53"],
    ["MEDIUM", "#FFCC00"],
    ["HARD", "#E6E6E6"],
    ["INTERMEDIATE", "#00A651"],
    ["WET", "#0077FF"],
  ])("maps %s to its color", (compound, expected) => {
    expect(getCompoundColor(compound)).toBe(expected);
  });

  it("normalizes INTER/INTERS to intermediate's color", () => {
    expect(getCompoundColor("INTER")).toBe("#00A651");
    expect(getCompoundColor("INTERS")).toBe("#00A651");
  });

  it("normalizes WETS to wet's color", () => {
    expect(getCompoundColor("WETS")).toBe("#0077FF");
  });

  it("is case-insensitive", () => {
    expect(getCompoundColor("soft")).toBe("#EA3C53");
  });

  it("falls back to a translucent default for an unknown/null/undefined compound", () => {
    expect(getCompoundColor("UNKNOWN")).toBe("rgba(255,255,255,0.4)");
    expect(getCompoundColor(null)).toBe("rgba(255,255,255,0.4)");
    expect(getCompoundColor(undefined)).toBe("rgba(255,255,255,0.4)");
  });
});

describe("getCompoundInitial", () => {
  it.each([
    ["SOFT", "S"],
    ["MEDIUM", "M"],
    ["HARD", "H"],
    ["INTERMEDIATE", "I"],
    ["WET", "W"],
  ])("maps %s to its initial", (compound, expected) => {
    expect(getCompoundInitial(compound)).toBe(expected);
  });

  it("falls back to a dash for an unknown compound", () => {
    expect(getCompoundInitial("UNKNOWN")).toBe("-");
  });
});

describe("getCompoundBadgeStyle", () => {
  it("returns bg/fg/border for each known compound", () => {
    expect(getCompoundBadgeStyle("SOFT")).toEqual({ bg: "#EA3C53", fg: "#FFFFFF", border: "#EA3C53" });
    expect(getCompoundBadgeStyle("MEDIUM")).toEqual({ bg: "#FFCC00", fg: "#000000", border: "#FFCC00" });
    expect(getCompoundBadgeStyle("HARD")).toEqual({ bg: "#FFFFFF", fg: "#000000", border: "#000000" });
    expect(getCompoundBadgeStyle("INTERMEDIATE")).toEqual({ bg: "#00A651", fg: "#FFFFFF", border: "#00A651" });
    expect(getCompoundBadgeStyle("WET")).toEqual({ bg: "#0077FF", fg: "#FFFFFF", border: "#0077FF" });
  });

  it("falls back to a transparent style for an unknown compound", () => {
    expect(getCompoundBadgeStyle("UNKNOWN")).toEqual({
      bg: "transparent",
      fg: "rgba(255,255,255,0.7)",
      border: "rgba(255,255,255,0.4)",
    });
  });
});

describe("getCompoundIconUrl", () => {
  it("returns a non-null URL for each known compound", () => {
    expect(getCompoundIconUrl("SOFT")).toBeTruthy();
    expect(getCompoundIconUrl("MEDIUM")).toBeTruthy();
    expect(getCompoundIconUrl("HARD")).toBeTruthy();
    expect(getCompoundIconUrl("INTERMEDIATE")).toBeTruthy();
    expect(getCompoundIconUrl("WET")).toBeTruthy();
  });

  it("returns null for an unknown compound", () => {
    expect(getCompoundIconUrl("UNKNOWN")).toBeNull();
  });
});
