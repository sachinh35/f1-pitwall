import React from "react";
import { useParams } from "react-router";
import { useLiveSessionState } from "../hooks/useLiveSessionState";
import QualifyingDashboard from "./QualifyingDashboard";
import RaceDashboard from "./RaceDashboard";

/**
 * Route target for /live-stream/:streamId. Owns nothing about rendering itself - just
 * connects (via useLiveSessionState) and picks which dashboard to render based on the
 * session's actual type, which isn't known until SessionInfo's first message arrives.
 * QualifyingDashboard and RaceDashboard are otherwise fully independent of each other; this
 * is the only place that knows both exist.
 */
const LiveSession: React.FC = () => {
  const { streamId } = useParams<{ streamId: string }>();
  const session = useLiveSessionState(streamId);

  if (session.state.sessionInfo.Type === "Qualifying") {
    return <QualifyingDashboard session={session} />;
  }
  return <RaceDashboard session={session} />;
};

export default LiveSession;
