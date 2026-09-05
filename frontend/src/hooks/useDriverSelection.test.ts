import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useDriverSelection } from "./useDriverSelection";

describe("useDriverSelection", () => {
  it("starts with no drivers selected", () => {
    const { result } = renderHook(() => useDriverSelection());
    expect(result.current.selectedDrivers).toEqual([]);
  });

  it("selects a driver on first toggle", () => {
    const { result } = renderHook(() => useDriverSelection());
    act(() => result.current.toggleDriver(1));
    expect(result.current.selectedDrivers).toEqual([1]);
  });

  it("deselects a driver already selected", () => {
    const { result } = renderHook(() => useDriverSelection());
    act(() => result.current.toggleDriver(1));
    act(() => result.current.toggleDriver(1));
    expect(result.current.selectedDrivers).toEqual([]);
  });

  it("accumulates multiple selections in order", () => {
    const { result } = renderHook(() => useDriverSelection());
    act(() => result.current.toggleDriver(1));
    act(() => result.current.toggleDriver(2));
    act(() => result.current.toggleDriver(3));
    expect(result.current.selectedDrivers).toEqual([1, 2, 3]);
  });

  it("evicts the oldest selection once the cap is reached", () => {
    const { result } = renderHook(() => useDriverSelection());
    act(() => result.current.toggleDriver(1));
    act(() => result.current.toggleDriver(2));
    act(() => result.current.toggleDriver(3));
    act(() => result.current.toggleDriver(4));
    act(() => result.current.toggleDriver(5));
    expect(result.current.selectedDrivers).toEqual([2, 3, 4, 5]);
  });

  it("removing a driver from a full selection makes room without evicting another", () => {
    const { result } = renderHook(() => useDriverSelection());
    act(() => result.current.toggleDriver(1));
    act(() => result.current.toggleDriver(2));
    act(() => result.current.toggleDriver(3));
    act(() => result.current.toggleDriver(4));
    act(() => result.current.toggleDriver(2)); // deselect
    expect(result.current.selectedDrivers).toEqual([1, 3, 4]);
  });
});
