import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useCompareWidgets } from "./useCompareWidgets";

describe("useCompareWidgets", () => {
  it("starts with the default 3-widget layout", () => {
    const { result } = renderHook(() => useCompareWidgets());
    expect(result.current.compareWidgets).toEqual([
      { id: "compare-0", metric: "speed" },
      { id: "compare-1", metric: "throttle" },
      { id: "compare-2", metric: "brake" },
    ]);
  });

  it("adds a new widget defaulting to speed", () => {
    const { result } = renderHook(() => useCompareWidgets());
    act(() => result.current.addCompareWidget());
    expect(result.current.compareWidgets).toHaveLength(4);
    expect(result.current.compareWidgets[3]).toEqual({ id: "compare-3", metric: "speed" });
  });

  it("assigns each newly added widget a unique, increasing id", () => {
    const { result } = renderHook(() => useCompareWidgets());
    act(() => result.current.addCompareWidget());
    act(() => result.current.addCompareWidget());
    expect(result.current.compareWidgets[3].id).toBe("compare-3");
    expect(result.current.compareWidgets[4].id).toBe("compare-4");
  });

  it("updates a specific widget's metric without touching the others", () => {
    const { result } = renderHook(() => useCompareWidgets());
    act(() => result.current.updateCompareWidgetMetric("compare-1", "sector1"));
    expect(result.current.compareWidgets).toEqual([
      { id: "compare-0", metric: "speed" },
      { id: "compare-1", metric: "sector1" },
      { id: "compare-2", metric: "brake" },
    ]);
  });

  it("removes a widget by id", () => {
    const { result } = renderHook(() => useCompareWidgets());
    act(() => result.current.removeCompareWidget("compare-1"));
    expect(result.current.compareWidgets.map((w) => w.id)).toEqual(["compare-0", "compare-2"]);
  });
});
