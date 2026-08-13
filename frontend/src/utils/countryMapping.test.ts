import { describe, expect, it } from "vitest";
import { getCountryFlagEmoji, getCountryName } from "./countryMapping";

describe("getCountryFlagEmoji", () => {
  it("returns null for a null country code", () => {
    expect(getCountryFlagEmoji(null)).toBeNull();
  });

  it("returns null for an undefined country code", () => {
    expect(getCountryFlagEmoji(undefined)).toBeNull();
  });

  it("returns the mapped flag for a known code", () => {
    expect(getCountryFlagEmoji("GBR")).toBe("🇬🇧");
  });

  it("is case-insensitive", () => {
    expect(getCountryFlagEmoji("gbr")).toBe("🇬🇧");
  });

  it("falls back to a checkered flag for an unknown code", () => {
    expect(getCountryFlagEmoji("ZZZ")).toBe("🏁");
  });
});

describe("getCountryName", () => {
  it("returns null for a null country code", () => {
    expect(getCountryName(null)).toBeNull();
  });

  it("returns null for an undefined country code", () => {
    expect(getCountryName(undefined)).toBeNull();
  });

  it("returns the mapped name for a known code", () => {
    expect(getCountryName("JPN")).toBe("Japan");
  });

  it("is case-insensitive", () => {
    expect(getCountryName("jpn")).toBe("Japan");
  });

  it("falls back to the raw code for an unknown code", () => {
    expect(getCountryName("ZZZ")).toBe("ZZZ");
  });
});
