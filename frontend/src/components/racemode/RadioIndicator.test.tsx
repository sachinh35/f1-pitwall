import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RadioIndicator from "./RadioIndicator";
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
    speaker_role: "pit_wall",
    is_notable: false,
    notable_reason: null,
    ...overrides,
  };
}

describe("RadioIndicator", () => {
  it("renders nothing when there are no clips", () => {
    const { container } = render(<RadioIndicator clips={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no clip has a transcript yet", () => {
    const { container } = render(
      <RadioIndicator clips={[makeClip({ transcript: null, status: "downloading" })]} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("reveals the transcript on hover", () => {
    render(<RadioIndicator clips={[makeClip({})]} />);
    const badge = screen.getByTitle(/team radio/i);

    expect(screen.queryByText(/box this lap/i)).not.toBeInTheDocument();

    fireEvent.mouseEnter(badge);

    expect(screen.getByText(/box this lap/i)).toBeInTheDocument();
    expect(screen.getByText("LAP 12")).toBeInTheDocument();
  });

  it("reveals the transcript on keyboard focus as well as hover", () => {
    render(<RadioIndicator clips={[makeClip({})]} />);
    const badge = screen.getByTitle(/team radio/i);

    fireEvent.focus(badge);
    expect(screen.getByText(/box this lap/i)).toBeInTheDocument();

    fireEvent.blur(badge);
    expect(screen.queryByText(/box this lap/i)).not.toBeInTheDocument();
  });

  it("shows the qualifying segment instead of a lap number during qualifying", () => {
    render(<RadioIndicator clips={[makeClip({ lap_number: 12, qualifying_part: "Q2" })]} />);
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));
    expect(screen.getByText("Q2")).toBeInTheDocument();
    expect(screen.queryByText(/LAP 12/)).not.toBeInTheDocument();
  });

  it("boxes a notable message but never shows a notable_reason explanation", () => {
    const { container } = render(
      <RadioIndicator
        clips={[makeClip({ is_notable: true, notable_reason: "Driver retiring from the race" })]}
      />
    );
    const badge = container.querySelector(".radio-indicator-badge");
    expect(badge).not.toBeNull();
    expect(badge?.className).toContain("radio-indicator-notable");

    fireEvent.mouseEnter(badge as Element);
    expect(container.querySelector(".radio-indicator-msg-notable")).not.toBeNull();
    expect(screen.queryByText(/driver retiring from the race/i)).not.toBeInTheDocument();
  });

  it("is not visually marked notable when no clip is notable", () => {
    const { container } = render(<RadioIndicator clips={[makeClip({ is_notable: false })]} />);
    const badge = container.querySelector(".radio-indicator-badge");
    expect(badge?.className).not.toContain("radio-indicator-notable");
  });

  it("lists every transcribed clip for the driver newest-first (reverse chronological)", () => {
    render(
      <RadioIndicator
        clips={[
          makeClip({ id: 1, ts: "2026-07-23T12:00:00Z", transcript: "First message", lap_number: 12 }),
          makeClip({ id: 2, ts: "2026-07-23T12:05:00Z", transcript: "Second message", lap_number: 14 }),
        ]}
      />
    );
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));

    const transcripts = screen
      .getAllByText(/message/i)
      .map((el) => el.textContent);
    expect(transcripts).toEqual([`“Second message”`, `“First message”`]);
  });

  it("groups messages by qualifying segment, most-recent segment first, newest message first within each group", () => {
    render(
      <RadioIndicator
        clips={[
          makeClip({ id: 1, ts: "2026-07-23T12:00:00Z", transcript: "Q1 early", qualifying_part: "Q1" }),
          makeClip({ id: 2, ts: "2026-07-23T12:01:00Z", transcript: "Q1 late", qualifying_part: "Q1" }),
          makeClip({ id: 3, ts: "2026-07-23T12:30:00Z", transcript: "Q2 only", qualifying_part: "Q2" }),
        ]}
      />
    );
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));

    const labels = screen.getAllByText(/^Q[123]$/).map((el) => el.textContent);
    expect(labels).toEqual(["Q2", "Q1"]);

    const transcripts = screen.getAllByText(/^“/).map((el) => el.textContent);
    expect(transcripts).toEqual([`“Q2 only”`, `“Q1 late”`, `“Q1 early”`]);

    // No per-message LAP badge when a group header already covers it.
    expect(screen.queryByText(/^LAP \d/)).not.toBeInTheDocument();
  });

  it("does not render a group header outside qualifying (qualifying_part is null)", () => {
    const { container } = render(
      <RadioIndicator
        clips={[
          makeClip({ id: 1, ts: "2026-07-23T12:00:00Z", transcript: "First", qualifying_part: null }),
          makeClip({ id: 2, ts: "2026-07-23T12:05:00Z", transcript: "Second", qualifying_part: null }),
        ]}
      />
    );
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));
    expect(container.querySelector(".radio-indicator-group-label")).toBeNull();
  });

  it("skips clips with no transcript yet but still shows the transcribed ones", () => {
    render(
      <RadioIndicator
        clips={[
          makeClip({ id: 1, transcript: "Ready message" }),
          makeClip({ id: 2, transcript: null, status: "transcribing" }),
        ]}
      />
    );
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));
    expect(screen.getByText(/ready message/i)).toBeInTheDocument();
  });
});
