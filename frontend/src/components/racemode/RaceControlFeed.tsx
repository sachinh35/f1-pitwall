import React, { useMemo, useState } from "react";
import { RaceControlEntry } from "../../types/raceMode";

interface RaceControlFeedProps {
  messages: Record<string, RaceControlEntry>;
}

/** The backend normalizes RaceControlMessages.Category to exactly one of these four values
 * before it reaches the client (see live_session_pipeline.py's _normalize_race_control_category) -
 * this is just the client-side mirror of that same set, plus a defensive fallback to "Other"
 * for anything else (e.g. a stored/replayed message captured before that normalization existed). */
type RaceControlCategory = "Flag" | "SafetyCar" | "Drs" | "Other";

const CATEGORY_FILTERS: { value: RaceControlCategory; label: string }[] = [
  { value: "Flag", label: "Flag" },
  { value: "SafetyCar", label: "Safety Car" },
  { value: "Drs", label: "DRS" },
  { value: "Other", label: "Other" },
];

function normalizeCategory(category?: string): RaceControlCategory {
  if (category === "Flag" || category === "SafetyCar" || category === "Drs") return category;
  return "Other";
}

function categoryClass(category: RaceControlCategory): string {
  if (category === "Drs") return "cat-drs";
  if (category === "Flag") return "cat-flag";
  if (category === "SafetyCar") return "cat-safety-car";
  return "cat-other";
}

/** F1's RaceControlMessages Utc field carries no 'Z'/offset suffix (e.g. "2025-11-30T15:57:04")
 * but is always UTC - append 'Z' when it's missing so the Date is parsed as UTC, not as local
 * time (which is what a bare offset-less ISO string means per spec), then render it in the
 * browser's own local time zone. Previously this just regex-extracted the raw UTC HH:MM
 * substring and displayed it as-is, silently showing UTC time as if it were local. */
function formatTime(utc?: string): string {
  if (!utc) return "";
  const iso = /(Z|[+-]\d{2}:?\d{2})$/.test(utc) ? utc : `${utc}Z`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return utc;
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

const ALL_CATEGORIES = new Set<RaceControlCategory>(CATEGORY_FILTERS.map((c) => c.value));

const RaceControlFeed: React.FC<RaceControlFeedProps> = ({ messages }) => {
  const [activeFilters, setActiveFilters] = useState<Set<RaceControlCategory>>(ALL_CATEGORIES);

  const entries = useMemo(
    () =>
      Object.entries(messages)
        .map(([index, entry]) => ({ index: Number(index), entry, category: normalizeCategory(entry.Category) }))
        .sort((a, b) => b.index - a.index)
        .slice(0, 40),
    [messages]
  );

  const countsByCategory = useMemo(() => {
    const counts = new Map<RaceControlCategory, number>();
    for (const { category } of entries) {
      counts.set(category, (counts.get(category) ?? 0) + 1);
    }
    return counts;
  }, [entries]);

  const toggleFilter = (category: RaceControlCategory) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const visibleEntries = entries.filter(({ category }) => activeFilters.has(category));
  const allSelected = activeFilters.size === ALL_CATEGORIES.size;

  if (entries.length === 0) {
    return <div style={{ color: "var(--text-faint)", fontSize: 13 }}>No race control messages yet.</div>;
  }

  return (
    <div>
      <div className="rc-filter-bar" role="group" aria-label="Filter race control events by category">
        <button
          type="button"
          className={`rc-filter-chip${allSelected ? " active" : ""}`}
          onClick={() => setActiveFilters(new Set(ALL_CATEGORIES))}
        >
          All
        </button>
        {CATEGORY_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            className={`rc-filter-chip ${categoryClass(value)}${activeFilters.has(value) ? " active" : ""}`}
            aria-pressed={activeFilters.has(value)}
            onClick={() => toggleFilter(value)}
          >
            {label}
            <span className="rc-filter-chip-count">{countsByCategory.get(value) ?? 0}</span>
          </button>
        ))}
      </div>
      {visibleEntries.length === 0 ? (
        <div style={{ color: "var(--text-faint)", fontSize: 13 }}>No events match the selected filters.</div>
      ) : (
        <div className="rc-feed-list">
          {visibleEntries.map(({ index, entry, category }) => (
            <div key={index} className="rc-item">
              <span className="t mono">{formatTime(entry.Utc)}</span>
              {entry.Lap != null && (
                <span className="rc-lap mono" title={`Fired on lap ${entry.Lap}`}>
                  L{entry.Lap}
                </span>
              )}
              <span className={`cat ${categoryClass(category)}`}>{entry.Category ?? "Info"}</span>
              <span className="m">{entry.Message ?? entry.Status ?? ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RaceControlFeed;
