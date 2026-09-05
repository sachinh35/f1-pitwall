import { useRef, useState } from "react";
import { CompareMetric } from "../utils/compareMetrics";

export interface CompareWidgetConfig {
  id: string;
  metric: CompareMetric;
}

// Default view (first load) preserves the original fixed 3-band layout: Speed/Throttle/Brake,
// in that order, so nothing regresses for an existing user.
const DEFAULT_COMPARE_WIDGETS: CompareWidgetConfig[] = [
  { id: "compare-0", metric: "speed" },
  { id: "compare-1", metric: "throttle" },
  { id: "compare-2", metric: "brake" },
];

export interface CompareWidgets {
  compareWidgets: CompareWidgetConfig[];
  addCompareWidget: () => void;
  updateCompareWidgetMetric: (id: string, metric: CompareMetric) => void;
  removeCompareWidget: (id: string) => void;
}

/** Manages the Telemetry Compare panel's widget list - add/remove/reconfigure - independent
 * of the live session data those widgets go on to read (telemetryRef etc.), so this state
 * never needs to reset just because the underlying stream reconnects. */
export function useCompareWidgets(): CompareWidgets {
  const [compareWidgets, setCompareWidgets] = useState<CompareWidgetConfig[]>(DEFAULT_COMPARE_WIDGETS);
  // Monotonic counter backing each new widget's React key - a ref (not state) since it's an
  // implementation detail that should never itself trigger a re-render.
  const nextId = useRef(DEFAULT_COMPARE_WIDGETS.length);

  const addCompareWidget = () => {
    const id = `compare-${nextId.current++}`;
    setCompareWidgets((prev) => [...prev, { id, metric: "speed" }]);
  };

  const updateCompareWidgetMetric = (id: string, metric: CompareMetric) => {
    setCompareWidgets((prev) => prev.map((w) => (w.id === id ? { ...w, metric } : w)));
  };

  const removeCompareWidget = (id: string) => {
    setCompareWidgets((prev) => prev.filter((w) => w.id !== id));
  };

  return { compareWidgets, addCompareWidget, updateCompareWidgetMetric, removeCompareWidget };
}
