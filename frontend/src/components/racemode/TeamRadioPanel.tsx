import React, { useEffect, useRef, useState } from "react";
import { getRosterEntry } from "../../data/driverRoster";
import { TeamRadioClip } from "../../types/raceMode";
import { radioBadgeLabel } from "./radioLabel";

interface TeamRadioPanelProps {
  clips: TeamRadioClip[];
}

const AUDIO_BASE_URL = "http://localhost:8000/audio";

function formatStatus(status: TeamRadioClip["status"]): string {
  switch (status) {
    case "pending":
      return "Incoming…";
    case "downloading":
      return "Downloading…";
    case "downloaded":
      return "Playable — transcribing…";
    case "transcribing":
      return "Transcribing…";
    case "failed_download":
      return "Download failed";
    case "failed_transcription":
      return "Transcription failed (still playable)";
    default:
      return "";
  }
}

/** Chat alignment bucket. "unclear" and not-yet-analyzed (null, before Gemini analysis has run)
 * both fall back to the centered/neutral layout - we shouldn't guess a side for something the
 * classifier itself wasn't sure about, or for a clip that hasn't been classified yet. */
function alignmentClass(speakerRole: TeamRadioClip["speaker_role"]): string {
  if (speakerRole === "pit_wall") return "radio-msg-pit_wall";
  if (speakerRole === "driver") return "radio-msg-driver";
  return "radio-msg-unclear";
}

const TeamRadioPanel: React.FC<TeamRadioPanelProps> = ({ clips }) => {
  const sorted = [...clips].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());

  // Exactly one clip may play at a time - clicking a second clip's play button must stop
  // whatever's currently playing first, and clicking the currently-playing clip's own
  // button pauses it, rather than starting an overlapping second Audio instance (the bug
  // this fixes: every click created a brand-new `new Audio(...)`, so N clicks meant N
  // clips playing simultaneously).
  const [playingId, setPlayingId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopPlayback = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlayingId(null);
  };

  const togglePlay = (clip: TeamRadioClip) => {
    if (playingId === clip.id) {
      stopPlayback();
      return;
    }
    stopPlayback();
    if (!clip.audio_path) return;
    const audio = new Audio(`${AUDIO_BASE_URL}/${clip.audio_path}`);
    audio.addEventListener("ended", () => setPlayingId((id) => (id === clip.id ? null : id)));
    audio.play().catch((err) => console.error(err));
    audioRef.current = audio;
    setPlayingId(clip.id);
  };

  // Never leave audio playing after the panel itself goes away (session switch, unmount).
  useEffect(() => () => audioRef.current?.pause(), []);

  if (sorted.length === 0) {
    return <div style={{ color: "var(--text-faint)", fontSize: 13 }}>No team radio yet.</div>;
  }

  return (
    <div className="radio-chat">
      {sorted.map((clip) => {
        const roster = getRosterEntry(clip.driver_number);
        const playable =
          Boolean(clip.audio_path) &&
          clip.status !== "pending" &&
          clip.status !== "downloading" &&
          clip.status !== "failed_download";
        const notable = clip.is_notable === true;
        const badge = radioBadgeLabel(clip);
        const playing = playingId === clip.id;

        return (
          <div
            key={clip.id}
            className={`radio-msg ${alignmentClass(clip.speaker_role)}${notable ? " radio-msg-notable" : ""}`}
          >
            <div className="radio-item-head">
              <button
                className="radio-play-btn"
                disabled={!playable}
                aria-label={playing ? "Pause" : "Play"}
                onClick={() => togglePlay(clip)}
              >
                {playing ? "❚❚" : "▶"}
              </button>
              <span className="radio-driver" style={{ color: roster.teamColor }}>
                {roster.tla}
              </span>
              {badge != null && <span className="radio-lap">{badge}</span>}
              {notable && <span className="radio-notable-tag">● Notable</span>}
            </div>
            {clip.transcript ? (
              <div className="radio-transcript">&ldquo;{clip.transcript}&rdquo;</div>
            ) : (
              <div className="radio-status">{formatStatus(clip.status)}</div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default TeamRadioPanel;
