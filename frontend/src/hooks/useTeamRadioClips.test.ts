import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTeamRadioClips } from "./useTeamRadioClips";
import { getTeamRadioForSession } from "../services/api";
import { TeamRadioClip } from "../types/raceMode";

vi.mock("../services/api", () => ({
  getTeamRadioForSession: vi.fn(),
}));

const mockedGetTeamRadioForSession = vi.mocked(getTeamRadioForSession);

beforeEach(() => {
  mockedGetTeamRadioForSession.mockReset();
});

function buildClip(id: number, driverNumber: number): TeamRadioClip {
  return {
    id,
    session_key: 9850,
    driver_number: driverNumber,
    lap_number: 1,
    qualifying_part: null,
    ts: "2026-01-01T00:00:00Z",
    audio_path: `clip-${id}.mp3`,
    transcript: null,
    status: "downloaded",
    error: null,
    transcribed_at: null,
    speaker_role: null,
    is_notable: null,
    notable_reason: null,
  };
}

describe("useTeamRadioClips", () => {
  it("does not fetch when there is no session key yet", () => {
    renderHook(() => useTeamRadioClips(null));
    expect(mockedGetTeamRadioForSession).not.toHaveBeenCalled();
  });

  it("fetches clips once a session key is available", async () => {
    mockedGetTeamRadioForSession.mockResolvedValue([buildClip(1, 44)]);
    const { result } = renderHook(() => useTeamRadioClips(9850));

    await waitFor(() => expect(result.current.clips).toHaveLength(1));
    expect(mockedGetTeamRadioForSession).toHaveBeenCalledWith(9850);
  });

  it("refresh() triggers another fetch", async () => {
    mockedGetTeamRadioForSession.mockResolvedValue([]);
    const { result } = renderHook(() => useTeamRadioClips(9850));
    await waitFor(() => expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(1));

    mockedGetTeamRadioForSession.mockResolvedValue([buildClip(1, 44)]);
    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.clips).toHaveLength(1));
    expect(mockedGetTeamRadioForSession).toHaveBeenCalledTimes(2);
  });

  it("reset() clears clips immediately", async () => {
    mockedGetTeamRadioForSession.mockResolvedValue([buildClip(1, 44)]);
    const { result } = renderHook(() => useTeamRadioClips(9850));
    await waitFor(() => expect(result.current.clips).toHaveLength(1));

    act(() => result.current.reset());

    expect(result.current.clips).toEqual([]);
  });

  it("logs and swallows a fetch failure rather than throwing", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockedGetTeamRadioForSession.mockRejectedValue(new Error("boom"));

    renderHook(() => useTeamRadioClips(9850));

    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    consoleError.mockRestore();
  });
});
