import React, { useState } from "react";
import { TeamRadioClip } from "../../types/raceMode";
import { radioBadgeLabel } from "./radioLabel";

interface RadioIndicatorProps {
  /** Every radio clip captured for this driver this session, any order - sorted and
   * filtered to transcribed-only internally. */
  clips: TeamRadioClip[];
}

interface RadioGroup {
  qualifyingPart: string | null;
  clips: TeamRadioClip[];
}

/** Newest message first overall, then bucketed by qualifying segment so Q1/Q2/Q3 never
 * interleave - each group keeps its own newest-first order, and groups themselves come out
 * most-recent-segment-first since segments never overlap in time. Outside qualifying every
 * clip's qualifying_part is null, which collapses to a single ungrouped (no header) bucket. */
function groupByQualifyingPart(clips: TeamRadioClip[]): RadioGroup[] {
  const sorted = [...clips].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  const groups: RadioGroup[] = [];
  for (const clip of sorted) {
    const current = groups[groups.length - 1];
    if (current && current.qualifyingPart === clip.qualifying_part) {
      current.clips.push(clip);
    } else {
      groups.push({ qualifyingPart: clip.qualifying_part, clips: [clip] });
    }
  }
  return groups;
}

const RadioIndicator: React.FC<RadioIndicatorProps> = ({ clips }) => {
  const [open, setOpen] = useState(false);

  const transcribed = clips.filter((clip) => clip.transcript);
  if (transcribed.length === 0) return null;

  const anyNotable = transcribed.some((clip) => clip.is_notable === true);
  const groups = groupByQualifyingPart(transcribed);

  return (
    <span
      className={`radio-indicator-badge${anyNotable ? " radio-indicator-notable" : ""}`}
      tabIndex={0}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      title={anyNotable ? "Notable team radio" : "Team radio"}
    >
      ((•))
      {open && (
        <span className="radio-indicator-popover">
          {groups.map((group) => (
            <span key={group.qualifyingPart ?? `race-${group.clips[0].id}`} className="radio-indicator-group">
              {group.qualifyingPart != null && (
                <span className="radio-indicator-group-label">{group.qualifyingPart}</span>
              )}
              {group.clips.map((clip) => {
                // The group header already conveys the segment - only fall back to a
                // per-message badge (LAP N) when there's no group header covering it.
                const badge = group.qualifyingPart == null ? radioBadgeLabel(clip) : null;
                const notable = clip.is_notable === true;
                return (
                  <span
                    key={clip.id}
                    className={`radio-indicator-msg${notable ? " radio-indicator-msg-notable" : ""}`}
                  >
                    {badge != null && <span className="radio-indicator-popover-lap">{badge}</span>}
                    <span className="radio-indicator-popover-transcript">&ldquo;{clip.transcript}&rdquo;</span>
                  </span>
                );
              })}
            </span>
          ))}
        </span>
      )}
    </span>
  );
};

export default RadioIndicator;
