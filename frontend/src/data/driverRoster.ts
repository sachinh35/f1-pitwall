/**
 * Static fallback driver/team roster.
 *
 * F1's live timing DriverList topic never actually carries names, teams, or
 * colours - confirmed by scanning the largest DriverList payload across a
 * full captured race: every message only ever contains a grid "Line" number.
 * This table is the last-resort fallback for identity, used only until the
 * backend's own OpenF1-backed roster fetch (broadcast as the "driver_roster"
 * SSE event/snapshot field, see setLiveRoster below) arrives for the current
 * session - which is also what correctly reflects reserve/substitute drivers,
 * since this static table can't. Still needs a yearly update as a baseline.
 */
export interface RosterEntry {
  driverNumber: number;
  tla: string;
  fullName: string;
  team: string;
  teamColor: string;
}

// 2026 race-seat lineup (22 drivers, 11 teams - Audi and Cadillac both joined
// for 2026, taking the grid from 10 teams to 11). Driver numbers verified
// against formula1.com's 2026 driver-numbers announcement - note several
// changed from 2025 (Verstappen #1->#3, Norris #4->#1, Tsunoda moved to a
// Red Bull reserve role with Lindblad taking Racing Bulls' second seat).
//
// Team colors sourced from github.com/Mahshadn/f1-constructors-colour-codes
// (2026-season.md), which itself flags them as unofficial approximations
// pending verification against real broadcast graphics. Cadillac's listed
// primary is white (#FFFFFF) - used as-is here rather than substituted with
// something more visible on a dark UI, to stay faithful to that source.
export const DRIVER_ROSTER: Record<number, RosterEntry> = {
  1: { driverNumber: 1, tla: "NOR", fullName: "Lando Norris", team: "McLaren", teamColor: "#F58020" },
  3: { driverNumber: 3, tla: "VER", fullName: "Max Verstappen", team: "Red Bull Racing", teamColor: "#3671C6" },
  5: { driverNumber: 5, tla: "BOR", fullName: "Gabriel Bortoleto", team: "Audi", teamColor: "#F50537" },
  6: { driverNumber: 6, tla: "HAD", fullName: "Isack Hadjar", team: "Racing Bulls", teamColor: "#6692FF" },
  10: { driverNumber: 10, tla: "GAS", fullName: "Pierre Gasly", team: "Alpine", teamColor: "#0093CC" },
  11: { driverNumber: 11, tla: "PER", fullName: "Sergio Perez", team: "Cadillac", teamColor: "#FFFFFF" },
  12: { driverNumber: 12, tla: "ANT", fullName: "Kimi Antonelli", team: "Mercedes", teamColor: "#27F4D2" },
  14: { driverNumber: 14, tla: "ALO", fullName: "Fernando Alonso", team: "Aston Martin", teamColor: "#229971" },
  16: { driverNumber: 16, tla: "LEC", fullName: "Charles Leclerc", team: "Ferrari", teamColor: "#E8002D" },
  18: { driverNumber: 18, tla: "STR", fullName: "Lance Stroll", team: "Aston Martin", teamColor: "#229971" },
  23: { driverNumber: 23, tla: "ALB", fullName: "Alexander Albon", team: "Williams", teamColor: "#64C4FF" },
  27: { driverNumber: 27, tla: "HUL", fullName: "Nico Hulkenberg", team: "Audi", teamColor: "#F50537" },
  30: { driverNumber: 30, tla: "LAW", fullName: "Liam Lawson", team: "Racing Bulls", teamColor: "#6692FF" },
  31: { driverNumber: 31, tla: "OCO", fullName: "Esteban Ocon", team: "Haas", teamColor: "#B6BABD" },
  41: { driverNumber: 41, tla: "LIN", fullName: "Arvid Lindblad", team: "Racing Bulls", teamColor: "#6692FF" },
  43: { driverNumber: 43, tla: "COL", fullName: "Franco Colapinto", team: "Alpine", teamColor: "#0093CC" },
  44: { driverNumber: 44, tla: "HAM", fullName: "Lewis Hamilton", team: "Ferrari", teamColor: "#E8002D" },
  55: { driverNumber: 55, tla: "SAI", fullName: "Carlos Sainz", team: "Williams", teamColor: "#64C4FF" },
  63: { driverNumber: 63, tla: "RUS", fullName: "George Russell", team: "Mercedes", teamColor: "#27F4D2" },
  77: { driverNumber: 77, tla: "BOT", fullName: "Valtteri Bottas", team: "Cadillac", teamColor: "#FFFFFF" },
  81: { driverNumber: 81, tla: "PIA", fullName: "Oscar Piastri", team: "McLaren", teamColor: "#F58020" },
  87: { driverNumber: 87, tla: "BEA", fullName: "Oliver Bearman", team: "Haas", teamColor: "#B6BABD" },
};

/** Team accent colors keyed by team name - used to resolve a color for drivers not in
 * DRIVER_ROSTER (e.g. a reserve driver picked during pre-race lineup confirmation). */
export const TEAM_COLORS: Record<string, string> = {
  McLaren: "#F58020",
  "Red Bull Racing": "#3671C6",
  Audi: "#F50537",
  "Racing Bulls": "#6692FF",
  Alpine: "#0093CC",
  Cadillac: "#FFFFFF",
  Mercedes: "#27F4D2",
  "Aston Martin": "#229971",
  Ferrari: "#E8002D",
  Williams: "#64C4FF",
  Haas: "#B6BABD",
};

const FALLBACK_ENTRY = (driverNumber: number): RosterEntry => ({
  driverNumber,
  tla: String(driverNumber),
  fullName: `Driver ${driverNumber}`,
  team: "Unknown",
  teamColor: "#8b93a3",
});

/**
 * The roster fetched from the backend for the current live/simulated session
 * (see RaceMode.tsx), keyed by driver number. Module-level like DRIVER_ROSTER
 * itself, so every leaf component that already calls getRosterEntry() picks
 * it up automatically without prop-drilling a roster map through the tree.
 */
let liveRoster: Record<number, RosterEntry> = {};

export function setLiveRoster(entries: Record<number, RosterEntry>): void {
  liveRoster = entries;
}

/** Call when a stream disconnects/switches sessions, so a new session never starts out showing
 * the previous one's roster before its own driver_roster event/snapshot arrives. */
export function clearLiveRoster(): void {
  liveRoster = {};
}

/** Backend team_colour values come from OpenF1 as bare hex, no leading "#". */
function normalizeHexColor(color: string | undefined, fallback: string): string {
  if (!color) return fallback;
  return color.startsWith("#") ? color : `#${color}`;
}

export interface DriverRosterWireEntry {
  driver_number: number;
  broadcast_name?: string | null;
  full_name: string;
  name_acronym: string;
  team_name?: string | null;
  team_colour?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  headshot_url?: string | null;
  country_code?: string | null;
}

export function rosterEntryFromWire(wire: DriverRosterWireEntry): RosterEntry {
  const fallback = FALLBACK_ENTRY(wire.driver_number);
  return {
    driverNumber: wire.driver_number,
    tla: wire.name_acronym || fallback.tla,
    fullName: wire.full_name || fallback.fullName,
    team: wire.team_name || fallback.team,
    teamColor: normalizeHexColor(wire.team_colour ?? undefined, fallback.teamColor),
  };
}

export function getRosterEntry(driverNumber: number): RosterEntry {
  return liveRoster[driverNumber] ?? DRIVER_ROSTER[driverNumber] ?? FALLBACK_ENTRY(driverNumber);
}
