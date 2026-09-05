import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useQualifyingResults } from "./useQualifyingResults";
import { getQualifyingResults, QualifyingResultEntry } from "../services/api";

vi.mock("../services/api", () => ({
  getQualifyingResults: vi.fn(),
}));

const mockedGetQualifyingResults = vi.mocked(getQualifyingResults);

function buildEntry(driverNumber: number, position: number): QualifyingResultEntry {
  return { driver_number: driverNumber, position, best_lap_seconds: 80, gap_to_leader_seconds: 0, eliminated: false };
}

beforeEach(() => {
  mockedGetQualifyingResults.mockReset();
});

describe("useQualifyingResults", () => {
  it("does not fetch when there is no session key yet", () => {
    renderHook(() => useQualifyingResults(null, null));
    expect(mockedGetQualifyingResults).not.toHaveBeenCalled();
  });

  it("fetches results once a session key is available", async () => {
    mockedGetQualifyingResults.mockResolvedValue({ Q1: [buildEntry(1, 1)] });
    const { result } = renderHook(() => useQualifyingResults(9850, "Q1"));

    await waitFor(() => expect(result.current.results.Q1).toHaveLength(1));
    expect(mockedGetQualifyingResults).toHaveBeenCalledWith(9850);
  });

  it("refetches when qualifyingPart advances", async () => {
    mockedGetQualifyingResults.mockResolvedValue({ Q1: [buildEntry(1, 1)] });
    const { result, rerender } = renderHook(
      ({ part }) => useQualifyingResults(9850, part),
      { initialProps: { part: "Q1" as string | null } }
    );
    await waitFor(() => expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(1));

    mockedGetQualifyingResults.mockResolvedValue({ Q1: [buildEntry(1, 1)], Q2: [buildEntry(1, 1)] });
    rerender({ part: "Q2" });

    await waitFor(() => expect(result.current.results.Q2).toHaveLength(1));
    expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(2);
  });

  it("does not refetch on an unrelated re-render with the same sessionKey/part", async () => {
    mockedGetQualifyingResults.mockResolvedValue({ Q1: [buildEntry(1, 1)] });
    const { rerender } = renderHook(({ part }) => useQualifyingResults(9850, part), {
      initialProps: { part: "Q1" as string | null },
    });
    await waitFor(() => expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(1));

    rerender({ part: "Q1" });

    expect(mockedGetQualifyingResults).toHaveBeenCalledTimes(1);
  });

  it("reset() clears results immediately", async () => {
    mockedGetQualifyingResults.mockResolvedValue({ Q1: [buildEntry(1, 1)] });
    const { result } = renderHook(() => useQualifyingResults(9850, "Q1"));
    await waitFor(() => expect(result.current.results.Q1).toHaveLength(1));

    act(() => result.current.reset());

    expect(result.current.results).toEqual({});
  });

  it("logs and swallows a fetch failure rather than throwing", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockedGetQualifyingResults.mockRejectedValue(new Error("boom"));

    renderHook(() => useQualifyingResults(9850, "Q1"));

    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    consoleError.mockRestore();
  });
});
