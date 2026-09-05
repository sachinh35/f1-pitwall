import { useCallback, useEffect, useState } from "react";
import { getTeamRadioForSession } from "../services/api";
import { TeamRadioClip } from "../types/raceMode";

export interface TeamRadioClips {
  clips: TeamRadioClip[];
  /** Re-fetches the full clip list - call whenever the stream reports a new/updated clip
   * (RADIO_CLIP_READY/RADIO_TRANSCRIPT_READY/RADIO_ANALYSIS_READY). */
  refresh: () => void;
  /** Clears the clip list immediately, without waiting on a fetch - call when reconnecting
   * to a different stream so the previous session's clips don't linger on screen. */
  reset: () => void;
}

/** Fetches (and re-fetches on demand) a session's team radio clips - shared by TimingTower's
 * per-row radio indicator and TeamRadioPanel, which read the exact same list rather than each
 * running their own fetch against the same endpoint. */
export function useTeamRadioClips(sessionKey: number | null): TeamRadioClips {
  const [clips, setClips] = useState<TeamRadioClip[]>([]);
  const [refreshSignal, setRefreshSignal] = useState(0);

  const refetch = useCallback(async () => {
    if (sessionKey == null) return;
    try {
      setClips(await getTeamRadioForSession(sessionKey));
    } catch (err) {
      console.error("Failed to fetch team radio", err);
    }
  }, [sessionKey]);

  useEffect(() => {
    // refetch only sets state after an await (see above) - genuinely async, not a
    // synchronous effect-body setState; the linter's static analysis just can't see through
    // the function call to confirm that.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refetch();
  }, [refetch, refreshSignal]);

  const refresh = useCallback(() => setRefreshSignal((n) => n + 1), []);
  const reset = useCallback(() => setClips([]), []);

  return { clips, refresh, reset };
}
