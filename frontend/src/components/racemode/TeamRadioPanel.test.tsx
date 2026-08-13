import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TeamRadioPanel from "./TeamRadioPanel";
import { TeamRadioClip } from "../../types/raceMode";

function makeClip(overrides: Partial<TeamRadioClip>): TeamRadioClip {
  return {
    id: 1,
    session_key: 9001,
    driver_number: 3,
    lap_number: 12,
    qualifying_part: null,
    ts: "2026-07-23T12:00:00Z",
    audio_path: "clip.mp3",
    transcript: "Box this lap, box this lap.",
    status: "done",
    error: null,
    transcribed_at: "2026-07-23T12:00:05Z",
    speaker_role: null,
    is_notable: null,
    notable_reason: null,
    ...overrides,
  };
}

describe("TeamRadioPanel", () => {
  let playSpy: ReturnType<typeof vi.spyOn>;
  let pauseSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    playSpy = vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    pauseSpy = vi.spyOn(window.HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  it('renders "No team radio yet." when clips is empty', () => {
    render(<TeamRadioPanel clips={[]} />);
    expect(screen.getByText(/no team radio yet/i)).toBeInTheDocument();
  });

  it("renders driver TLA and transcript for a clip", () => {
    render(<TeamRadioPanel clips={[makeClip({})]} />);
    expect(screen.getByText("VER")).toBeInTheDocument();
    expect(screen.getByText(/box this lap, box this lap/i)).toBeInTheDocument();
  });

  it("gives pit_wall and driver clips visually distinct alignment classes", () => {
    const { container } = render(
      <TeamRadioPanel
        clips={[
          makeClip({ id: 1, speaker_role: "pit_wall", ts: "2026-07-23T12:00:00Z" }),
          makeClip({ id: 2, speaker_role: "driver", ts: "2026-07-23T12:01:00Z" }),
        ]}
      />
    );
    const pitWallMsg = container.querySelector(".radio-msg-pit_wall");
    const driverMsg = container.querySelector(".radio-msg-driver");
    expect(pitWallMsg).not.toBeNull();
    expect(driverMsg).not.toBeNull();
    expect(pitWallMsg?.className).not.toEqual(driverMsg?.className);
  });

  it("falls back to a neutral/centered class for unclear or unanalyzed clips", () => {
    const { container } = render(<TeamRadioPanel clips={[makeClip({ speaker_role: null })]} />);
    expect(container.querySelector(".radio-msg-unclear")).not.toBeNull();
  });

  it("marks a notable clip with a distinguishing class/marker", () => {
    const { container } = render(<TeamRadioPanel clips={[makeClip({ is_notable: true })]} />);
    expect(container.querySelector(".radio-msg-notable")).not.toBeNull();
    expect(screen.getByText(/notable/i)).toBeInTheDocument();
  });

  it("does not mark a non-notable clip as notable", () => {
    const { container } = render(<TeamRadioPanel clips={[makeClip({ is_notable: false })]} />);
    expect(container.querySelector(".radio-msg-notable")).toBeNull();
  });

  it("disables the play button while a clip is not yet playable", () => {
    render(<TeamRadioPanel clips={[makeClip({ status: "downloading", transcript: null })]} />);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(screen.getByText(/downloading/i)).toBeInTheDocument();
  });

  it("enables the play button once a clip is playable", () => {
    render(<TeamRadioPanel clips={[makeClip({ status: "done", audio_path: "clip.mp3" })]} />);
    const button = screen.getByRole("button");
    expect(button).not.toBeDisabled();
  });

  it("sorts clips newest-first by ts", () => {
    render(
      <TeamRadioPanel
        clips={[
          makeClip({ id: 1, driver_number: 3, ts: "2026-07-23T12:00:00Z" }),
          makeClip({ id: 2, driver_number: 16, ts: "2026-07-23T12:05:00Z" }),
        ]}
      />
    );
    const tlas = screen.getAllByText(/^(VER|LEC)$/).map((el) => el.textContent);
    expect(tlas).toEqual(["LEC", "VER"]);
  });

  it("shows a LAP N badge for a race clip (qualifying_part is null)", () => {
    render(<TeamRadioPanel clips={[makeClip({ lap_number: 15, qualifying_part: null })]} />);
    expect(screen.getByText("LAP 15")).toBeInTheDocument();
  });

  it("shows the qualifying segment instead of a lap number for a qualifying clip", () => {
    render(<TeamRadioPanel clips={[makeClip({ lap_number: 15, qualifying_part: "Q1" })]} />);
    expect(screen.getByText("Q1")).toBeInTheDocument();
    expect(screen.queryByText(/LAP 15/)).not.toBeInTheDocument();
  });

  it("renders no lap/segment badge when neither is known", () => {
    const { container } = render(<TeamRadioPanel clips={[makeClip({ lap_number: null, qualifying_part: null })]} />);
    expect(container.querySelector(".radio-lap")).toBeNull();
  });

  it("clicking play starts playback and swaps the button to a pause control", () => {
    render(<TeamRadioPanel clips={[makeClip({})]} />);
    playSpy.mockClear();
    pauseSpy.mockClear();
    const button = screen.getByRole("button", { name: "Play" });

    fireEvent.click(button);

    expect(playSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
  });

  it("clicking the currently-playing clip's button pauses it instead of starting a second one", () => {
    render(<TeamRadioPanel clips={[makeClip({})]} />);
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    playSpy.mockClear();
    pauseSpy.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));

    expect(pauseSpy).toHaveBeenCalledTimes(1);
    expect(playSpy).not.toHaveBeenCalled(); // never played a second time
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("playing a second clip stops the first - never two clips playing at once", () => {
    render(
      <TeamRadioPanel
        clips={[
          makeClip({ id: 1, driver_number: 3, ts: "2026-07-23T12:00:00Z" }),
          makeClip({ id: 2, driver_number: 16, ts: "2026-07-23T12:05:00Z" }),
        ]}
      />
    );
    // Sorted newest-first: clip 2 (LEC) then clip 1 (VER).
    const [secondButton, firstButton] = screen.getAllByRole("button");
    playSpy.mockClear();
    pauseSpy.mockClear();

    fireEvent.click(secondButton);
    expect(playSpy).toHaveBeenCalledTimes(1);

    fireEvent.click(firstButton);

    expect(pauseSpy).toHaveBeenCalledTimes(1); // stopped clip 2 before starting clip 1
    expect(playSpy).toHaveBeenCalledTimes(2);
    expect(secondButton).toHaveAccessibleName("Play");
    expect(firstButton).toHaveAccessibleName("Pause");
  });
});
