import { useCallback, useEffect, useState } from "react";
import { getQualifyingResults, QualifyingResultEntry } from "../services/api";

export interface QualifyingResults {
  /** Keyed by segment ("Q1"/"Q2"/"Q3") - a segment absent here just hasn't ended yet. */
  results: Record<string, QualifyingResultEntry[]>;
  /** Clears results immediately - call when reconnecting to a different stream so the
   * previous session's results don't linger on screen. */
  reset: () => void;
}

/**
 * Fetches a qualifying session's persisted segment results, refetching whenever
 * `qualifyingPart` advances (Q1->Q2->Q3) - that's exactly when the backend persists the
 * segment that just ended (see live/session_state.py's _snapshot_qualifying_results).
 * Also runs on initial connect (sessionKey becoming available) so a page loaded mid-Q2/Q3
 * picks up whichever earlier segments already finished before this connection existed.
 */
export function useQualifyingResults(
  sessionKey: number | null,
  qualifyingPart: string | null
): QualifyingResults {
  const [results, setResults] = useState<Record<string, QualifyingResultEntry[]>>({});

  useEffect(() => {
    if (sessionKey == null) return;
    let cancelled = false;
    getQualifyingResults(sessionKey)
      .then((fetched) => {
        if (!cancelled) setResults(fetched);
      })
      .catch((err) => console.error("Failed to fetch qualifying results", err));
    return () => {
      cancelled = true;
    };
  }, [sessionKey, qualifyingPart]);

  const reset = useCallback(() => setResults({}), []);

  return { results, reset };
}
