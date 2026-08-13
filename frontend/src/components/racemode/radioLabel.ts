import { TeamRadioClip } from "../../types/raceMode";

/**
 * The lap/segment badge shown on a radio clip: qualifying_part (e.g. "Q2") during
 * qualifying, since lap_number there is just a session-cumulative lap count with no
 * meaningful "current lap" - the same reason the timing tower hides lap numbers in
 * qualifying. Falls back to "LAP N" for a race/practice session. null if neither is known.
 */
export function radioBadgeLabel(clip: Pick<TeamRadioClip, "qualifying_part" | "lap_number">): string | null {
  if (clip.qualifying_part != null) return clip.qualifying_part;
  if (clip.lap_number != null) return `LAP ${clip.lap_number}`;
  return null;
}
