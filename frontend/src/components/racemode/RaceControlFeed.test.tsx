import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import RaceControlFeed from "./RaceControlFeed";

beforeAll(() => {
  // Fixed, non-UTC offset so a wrong "just display the raw UTC substring" implementation
  // is guaranteed to diverge from the correct local-time conversion in this test run,
  // regardless of the machine/CI runner's own real time zone.
  vi.stubEnv("TZ", "America/New_York");
});

afterAll(() => {
  vi.unstubAllEnvs();
});

describe("RaceControlFeed", () => {
  it('renders "No race control messages yet." when empty', () => {
    render(<RaceControlFeed messages={{}} />);
    expect(screen.getByText(/no race control messages yet/i)).toBeInTheDocument();
  });

  it("converts F1's offset-less UTC timestamp to the browser's local time, not a raw substring of the UTC string", () => {
    // F1's RaceControlMessages.Utc carries no 'Z'/offset suffix but is always UTC.
    // 2025-11-30T15:57:04 UTC -> 10:57 in America/New_York (UTC-5 in late November).
    render(
      <RaceControlFeed
        messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Flag", Message: "GREEN LIGHT" } }}
      />
    );
    expect(screen.getByText("10:57")).toBeInTheDocument();
    expect(screen.queryByText("15:57")).not.toBeInTheDocument();
  });

  it("renders the category and message text", () => {
    render(
      <RaceControlFeed
        messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Flag", Message: "GREEN LIGHT" } }}
      />
    );
    expect(screen.getByText("Flag", { selector: ".cat" })).toBeInTheDocument();
    expect(screen.getByText("GREEN LIGHT")).toBeInTheDocument();
  });

  it('renders an empty time for an entry with no Utc field', () => {
    render(<RaceControlFeed messages={{ "1": { Category: "Flag", Message: "GREEN LIGHT" } }} />);
    expect(screen.getByText("GREEN LIGHT")).toBeInTheDocument();
  });

  it("falls back to the raw string for an unparseable Utc value", () => {
    render(
      <RaceControlFeed messages={{ "1": { Utc: "not-a-real-timestamp", Category: "Flag", Message: "GREEN LIGHT" } }} />
    );
    expect(screen.getByText("not-a-real-timestamp")).toBeInTheDocument();
  });

  it("uses a Utc value verbatim (as UTC) when it already carries an explicit offset/Z suffix", () => {
    render(
      <RaceControlFeed messages={{ "1": { Utc: "2025-11-30T15:57:04Z", Category: "Flag", Message: "GREEN LIGHT" } }} />
    );
    expect(screen.getByText("10:57")).toBeInTheDocument();
  });

  it('defaults the category badge to "Info" when Category is missing', () => {
    render(<RaceControlFeed messages={{ "1": { Utc: "2025-11-30T15:57:04", Message: "SESSION STARTED" } }} />);
    expect(screen.getByText("Info", { selector: ".cat" })).toBeInTheDocument();
  });

  it("renders empty message text when neither Message nor Status is present", () => {
    const { container } = render(<RaceControlFeed messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Other" } }} />);
    expect(container.querySelector(".m")?.textContent).toBe("");
  });

  it("falls back to Status text when Message is absent", () => {
    render(<RaceControlFeed messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Other", Status: "TRACK CLEAR" } }} />);
    expect(screen.getByText("TRACK CLEAR")).toBeInTheDocument();
  });

  it("renders a lap marker when the entry carries a Lap number", () => {
    render(
      <RaceControlFeed
        messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Flag", Message: "GREEN LIGHT", Lap: 44 } }}
      />
    );
    const marker = screen.getByText("L44");
    expect(marker.title).toMatch(/lap 44/i);
  });

  it("omits the lap marker when the entry has no Lap number", () => {
    render(
      <RaceControlFeed
        messages={{ "1": { Utc: "2025-11-30T15:57:04", Category: "Flag", Message: "GREEN LIGHT" } }}
      />
    );
    expect(screen.queryByText(/^L\d+$/)).not.toBeInTheDocument();
  });

  it("sorts entries newest-first by message index", () => {
    render(
      <RaceControlFeed
        messages={{
          "1": { Utc: "2025-11-30T15:00:00", Category: "Other", Message: "First" },
          "2": { Utc: "2025-11-30T15:05:00", Category: "Other", Message: "Second" },
        }}
      />
    );
    const messages = screen.getAllByText(/^(First|Second)$/).map((el) => el.textContent);
    expect(messages).toEqual(["Second", "First"]);
  });

  describe("category filter", () => {
    const mixedMessages = {
      "1": { Utc: "2025-11-30T15:00:00", Category: "Flag", Message: "YELLOW FLAG" },
      "2": { Utc: "2025-11-30T15:01:00", Category: "SafetyCar", Message: "SAFETY CAR DEPLOYED" },
      "3": { Utc: "2025-11-30T15:02:00", Category: "Drs", Message: "DRS ENABLED" },
      "4": { Utc: "2025-11-30T15:03:00", Category: "Other", Message: "PIT LANE OPEN" },
    };

    it("shows every category by default, with a filter chip per category plus All", () => {
      render(<RaceControlFeed messages={mixedMessages} />);
      expect(screen.getByText("YELLOW FLAG")).toBeInTheDocument();
      expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeInTheDocument();
      expect(screen.getByText("DRS ENABLED")).toBeInTheDocument();
      expect(screen.getByText("PIT LANE OPEN")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^All$/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Safety Car/ })).toBeInTheDocument();
    });

    it("hides messages whose category is toggled off", () => {
      render(<RaceControlFeed messages={mixedMessages} />);
      fireEvent.click(screen.getByRole("button", { name: /^Flag/ }));

      expect(screen.queryByText("YELLOW FLAG")).not.toBeInTheDocument();
      expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeInTheDocument();
      expect(screen.getByText("DRS ENABLED")).toBeInTheDocument();
      expect(screen.getByText("PIT LANE OPEN")).toBeInTheDocument();
    });

    it("shows an empty-filter message when every category is toggled off", () => {
      render(<RaceControlFeed messages={mixedMessages} />);
      fireEvent.click(screen.getByRole("button", { name: /^Flag/ }));
      fireEvent.click(screen.getByRole("button", { name: /Safety Car/ }));
      fireEvent.click(screen.getByRole("button", { name: /^DRS/ }));
      fireEvent.click(screen.getByRole("button", { name: /^Other/ }));

      expect(screen.getByText(/no events match the selected filters/i)).toBeInTheDocument();
    });

    it("re-selecting a single previously-toggled-off category chip shows its messages again", () => {
      render(<RaceControlFeed messages={mixedMessages} />);
      const flagChip = screen.getByRole("button", { name: /^Flag/ });
      fireEvent.click(flagChip);
      expect(screen.queryByText("YELLOW FLAG")).not.toBeInTheDocument();

      fireEvent.click(flagChip);
      expect(screen.getByText("YELLOW FLAG")).toBeInTheDocument();
    });

    it("clicking All re-selects every category", () => {
      render(<RaceControlFeed messages={mixedMessages} />);
      fireEvent.click(screen.getByRole("button", { name: /^Flag/ }));
      expect(screen.queryByText("YELLOW FLAG")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /^All$/ }));
      expect(screen.getByText("YELLOW FLAG")).toBeInTheDocument();
    });

    it("treats an unrecognized category as Other for both display and filtering", () => {
      render(
        <RaceControlFeed
          messages={{ "1": { Utc: "2025-11-30T15:00:00", Category: "SessionStatus", Message: "SESSION ENDS" } }}
        />
      );
      expect(screen.getByText("SessionStatus")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /^Other/ }));
      expect(screen.queryByText("SESSION ENDS")).not.toBeInTheDocument();
    });
  });
});
