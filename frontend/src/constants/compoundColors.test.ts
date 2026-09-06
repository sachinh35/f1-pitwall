import { describe, expect, it } from "vitest";
import { getCompoundIconUrl } from "./compoundColors";

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

  it("returns null for a null or undefined compound", () => {
    expect(getCompoundIconUrl(null)).toBeNull();
    expect(getCompoundIconUrl(undefined)).toBeNull();
  });

  it("normalizes INTER/INTERS to the intermediate icon", () => {
    expect(getCompoundIconUrl("INTER")).toBe(getCompoundIconUrl("INTERMEDIATE"));
    expect(getCompoundIconUrl("INTERS")).toBe(getCompoundIconUrl("INTERMEDIATE"));
  });

  it("normalizes WETS to the wet icon", () => {
    expect(getCompoundIconUrl("WETS")).toBe(getCompoundIconUrl("WET"));
  });

  it("is case-insensitive", () => {
    expect(getCompoundIconUrl("soft")).toBe(getCompoundIconUrl("SOFT"));
  });
});
