import { SessionStatusData, TrackStatus } from "../types/raceMode";

/**
 * Track status codes observed directly in captured logs: "1" -> AllClear, "2" -> Yellow.
 * The other codes below (safety car / red / VSC) follow F1's commonly documented
 * numbering but weren't directly observed in this project's captures - callers always
 * show the real Message text regardless, so an imperfect color mapping for an
 * unconfirmed code degrades to "status-unknown" rather than showing something wrong.
 *
 * Shared by TrackStatusBanner (the full flag + weather panel) and TrackStatusFlag (the
 * compact top-of-page banner) so the two never drift on what counts as red/yellow/green.
 */
export function flagClass(status?: string): string {
  switch (status) {
    case "1":
      return "status-green";
    case "2":
    case "6":
    case "7":
      return "status-yellow";
    case "4":
    case "5":
      return "status-red";
    default:
      return "status-unknown";
  }
}

export interface FlagDisplay {
  text: string;
  className: string;
}

/**
 * TrackStatus and SessionStatus are two independent SignalR topics that don't always
 * change in lockstep: TrackStatus reflects local track/flag conditions (individual
 * sectors, marshal posts), while SessionStatus is the session's own start/stop state.
 * Confirmed live during a red-flag stoppage: marshals began clearing sectors and
 * TrackStatus cycled AllClear -> Yellow again within ~2 minutes of the red flag, while
 * SessionStatus correctly stayed "Aborted" for far longer - the session itself hadn't
 * resumed. Showing TrackStatus alone during that window looks exactly like the race
 * has gone back to green-flag racing when it's still stopped, so SessionStatus
 * "Aborted" overrides whatever TrackStatus currently says.
 */
export function resolveFlagDisplay(trackStatus: TrackStatus, sessionStatus?: SessionStatusData): FlagDisplay {
  if (sessionStatus?.Status === "Aborted") {
    return { text: "Race Suspended", className: "status-red" };
  }
  return { text: trackStatus.Message ?? "Unknown", className: flagClass(trackStatus.Status) };
}
