import { afterEach, describe, expect, it } from "vitest";
import { clearLiveRoster, DRIVER_ROSTER, getRosterEntry, rosterEntryFromWire, setLiveRoster } from "./driverRoster";

afterEach(() => {
  clearLiveRoster();
});

describe("getRosterEntry", () => {
  it("returns real roster data for a known driver number", () => {
    const entry = getRosterEntry(3);
    expect(entry.tla).toBe("VER");
    expect(entry.team).toBe("Red Bull Racing");
  });

  it("falls back to a generic entry for an unknown driver number", () => {
    const entry = getRosterEntry(999);
    expect(entry.tla).toBe("999");
    expect(entry.fullName).toBe("Driver 999");
    expect(entry.team).toBe("Unknown");
  });

  it("every roster entry has a valid 6-digit hex team color", () => {
    Object.values(DRIVER_ROSTER).forEach((entry) => {
      expect(entry.teamColor).toMatch(/^#[0-9A-Fa-f]{6}$/);
    });
  });

  it("has exactly 22 drivers, matching the 2026 grid (11 teams x 2)", () => {
    expect(Object.keys(DRIVER_ROSTER)).toHaveLength(22);
  });

  it("includes Cadillac, the 11th team new for 2026", () => {
    expect(getRosterEntry(11).team).toBe("Cadillac");
    expect(getRosterEntry(77).team).toBe("Cadillac");
  });

  it("shows Audi (not Kick Sauber) for both Audi-seat drivers", () => {
    expect(getRosterEntry(5).team).toBe("Audi");
    expect(getRosterEntry(5).teamColor).toBe("#F50537");
    expect(getRosterEntry(27).team).toBe("Audi");
    expect(getRosterEntry(27).teamColor).toBe("#F50537");
  });

  it("prefers a live-roster entry over the static fallback table", () => {
    setLiveRoster({ 1: { driverNumber: 1, tla: "TEST", fullName: "Test Driver", team: "Test Team", teamColor: "#123456" } });
    expect(getRosterEntry(1)).toEqual({
      driverNumber: 1,
      tla: "TEST",
      fullName: "Test Driver",
      team: "Test Team",
      teamColor: "#123456",
    });
  });

  it("falls back to the static table again after clearLiveRoster", () => {
    setLiveRoster({ 1: { driverNumber: 1, tla: "TEST", fullName: "Test Driver", team: "Test Team", teamColor: "#123456" } });
    clearLiveRoster();
    expect(getRosterEntry(1).tla).toBe("NOR");
  });
});

describe("rosterEntryFromWire", () => {
  it("maps a full wire entry, normalizing a bare hex color to include '#'", () => {
    const entry = rosterEntryFromWire({
      driver_number: 1,
      full_name: "Max Verstappen",
      name_acronym: "VER",
      team_name: "Red Bull Racing",
      team_colour: "3671C6",
    });
    expect(entry).toEqual({
      driverNumber: 1,
      tla: "VER",
      fullName: "Max Verstappen",
      team: "Red Bull Racing",
      teamColor: "#3671C6",
    });
  });

  it("leaves an already-prefixed hex color untouched", () => {
    expect(rosterEntryFromWire({ driver_number: 1, full_name: "X", name_acronym: "X", team_colour: "#ABCDEF" }).teamColor).toBe(
      "#ABCDEF"
    );
  });

  it("falls back to generic values for missing optional fields", () => {
    const entry = rosterEntryFromWire({ driver_number: 42, full_name: "", name_acronym: "" });
    expect(entry.tla).toBe("42");
    expect(entry.fullName).toBe("Driver 42");
    expect(entry.team).toBe("Unknown");
    expect(entry.teamColor).toBe("#8b93a3");
  });
});
