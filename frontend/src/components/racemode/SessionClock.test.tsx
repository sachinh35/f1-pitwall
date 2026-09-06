import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SessionClock from "./SessionClock";

describe("SessionClock", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a placeholder before any clock data has arrived", () => {
    render(<SessionClock lapCount={{}} extrapolatedClock={{}} isQualifying={false} qualifyingPart={null} />);
    expect(screen.getByText("--:--:--")).toBeInTheDocument();
  });

  it("displays the initial Remaining value from the feed", () => {
    render(
      <SessionClock
        lapCount={{ CurrentLap: 5 }}
        extrapolatedClock={{ Remaining: "01:59:59", Extrapolating: true }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("1:59:59")).toBeInTheDocument();
  });

  it(
    "ticks the remaining time down locally when Extrapolating is true - " +
      "regression test for the bug where the clock froze at whatever value F1 sent once",
    async () => {
      vi.useFakeTimers();
      render(
        <SessionClock
          lapCount={{ CurrentLap: 5 }}
          extrapolatedClock={{ Remaining: "01:59:59", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );

      expect(screen.getByText("1:59:59")).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(3000);

      expect(screen.getByText("1:59:56")).toBeInTheDocument();
    }
  );

  it("does not tick when Extrapolating is false", async () => {
    vi.useFakeTimers();
    render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "00:30:00", Extrapolating: false }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );

    await vi.advanceTimersByTimeAsync(5000);

    expect(screen.getByText("0:30:00")).toBeInTheDocument();
  });

  it(
    "shows the raw Remaining value as-is when Extrapolating is false, even with a stale " +
      "Utc - regression test for the bug where a pre-race snapshot (Remaining 02:00:00 as " +
      "of a now-past Utc) got silently decayed by wall-clock time since receipt and froze " +
      "on the wrong number",
    () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:52:50.000Z")); // 2m10s after Utc below

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{
            Remaining: "02:00:00",
            Utc: "2026-09-06T12:50:40.000Z",
            Extrapolating: false,
          }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );

      expect(screen.getByText("2:00:00")).toBeInTheDocument();
    }
  );

  it("re-anchors to a fresh value when a new ExtrapolatedClock event arrives", () => {
    const { rerender } = render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "01:00:00", Extrapolating: true }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("1:00:00")).toBeInTheDocument();

    rerender(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "00:45:00", Extrapolating: true }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("0:45:00")).toBeInTheDocument();
  });

  it("shows the current lap and a generic 'Remaining' label outside qualifying", () => {
    render(
      <SessionClock
        lapCount={{ CurrentLap: 5, TotalLaps: 57 }}
        extrapolatedClock={{}}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("Lap")).toBeInTheDocument();
    expect(screen.getByText("5 / 57")).toBeInTheDocument();
    expect(screen.getByText("Remaining")).toBeInTheDocument();
  });

  it("shows the qualifying segment instead of a lap count, with a segment-scoped remaining label", () => {
    render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "00:12:34", Extrapolating: false }}
        isQualifying={true}
        qualifyingPart="Q2"
      />
    );
    expect(screen.queryByText("Lap")).not.toBeInTheDocument();
    expect(screen.getByText("Q2")).toBeInTheDocument();
    expect(screen.getByText("Session")).toBeInTheDocument();
    expect(screen.getByText("Time Remaining (Q2)")).toBeInTheDocument();
  });

  it("falls back to a Q? placeholder when qualifying but the segment isn't known yet", () => {
    render(<SessionClock lapCount={{}} extrapolatedClock={{}} isQualifying={true} qualifyingPart={null} />);
    expect(screen.getByText("Q?")).toBeInTheDocument();
    expect(screen.getByText("Time Remaining")).toBeInTheDocument();
  });

  it("parses a MM:SS (no hours) Remaining value", () => {
    render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "05:30", Extrapolating: false }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("0:05:30")).toBeInTheDocument();
  });

  it("ignores a Remaining value with a valid-number but wrong part count (neither H:MM:SS nor MM:SS)", () => {
    render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "45", Extrapolating: false }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("--:--:--")).toBeInTheDocument();
  });

  it("ignores a malformed Remaining value (leaves the placeholder as-is)", () => {
    render(
      <SessionClock
        lapCount={{}}
        extrapolatedClock={{ Remaining: "not-a-time", Extrapolating: false }}
        isQualifying={false}
        qualifyingPart={null}
      />
    );
    expect(screen.getByText("--:--:--")).toBeInTheDocument();
  });

  it("does not tick when the interval fires before any Remaining value has anchored the clock", async () => {
    vi.useFakeTimers();
    render(
      <SessionClock lapCount={{}} extrapolatedClock={{ Extrapolating: true }} isQualifying={false} qualifyingPart={null} />
    );
    expect(screen.getByText("--:--:--")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(1000);

    expect(screen.getByText("--:--:--")).toBeInTheDocument();
  });

  describe("anchoring to F1's own Utc timestamp, not render time", () => {
    // Regression coverage for a real bug: anchoring to Date.now() meant a page
    // refresh - which re-delivers the same last-known Remaining value via the SSE
    // snapshot - made the countdown restart from that stale number instead of
    // continuing from the true current remaining time.

    it("accounts for time already elapsed since Utc on first render (simulates a refresh)", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-01-01T00:02:00.000Z")); // "now"

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{ Remaining: "00:10:00", Utc: "2026-01-01T00:00:00.000Z", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );

      // 2 minutes really elapsed since Utc -> true remaining is 8:00, not the raw 10:00.
      expect(screen.getByText("0:08:00")).toBeInTheDocument();
    });

    it("continues ticking down from the Utc-adjusted value, not from the raw Remaining", async () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-01-01T00:02:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{ Remaining: "00:10:00", Utc: "2026-01-01T00:00:00.000Z", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );
      expect(screen.getByText("0:08:00")).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(3000);

      expect(screen.getByText("0:07:57")).toBeInTheDocument();
    });

    it("falls back to render time when Utc is absent (unchanged prior behavior)", () => {
      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{ Remaining: "00:10:00", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );
      expect(screen.getByText("0:10:00")).toBeInTheDocument();
    });

    it("clamps to zero rather than going negative for a very stale Utc", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-01-01T01:00:00.000Z")); // an hour after Utc

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{ Remaining: "00:10:00", Utc: "2026-01-01T00:00:00.000Z", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );

      expect(screen.getByText("0:00:00")).toBeInTheDocument();
    });
  });

  describe("Starts In countdown", () => {
    it("shows no countdown when startDate is not provided", () => {
      render(<SessionClock lapCount={{}} extrapolatedClock={{}} isQualifying={false} qualifyingPart={null} />);
      expect(screen.queryByText("Starts In")).not.toBeInTheDocument();
    });

    it("converts StartDate + GmtOffset to a UTC instant and counts down to it", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T15:00:00"
          gmtOffset="02:00:00"
        />
      );

      // Local StartDate 15:00:00 at UTC+2 -> UTC 13:00:00, i.e. 10 minutes from "now".
      expect(screen.getByText("0:10:00")).toBeInTheDocument();
      expect(screen.getByText("Starts In")).toBeInTheDocument();
    });

    it("ticks the countdown down every second", async () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T15:00:00"
          gmtOffset="02:00:00"
        />
      );
      expect(screen.getByText("0:10:00")).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(3000);

      expect(screen.getByText("0:09:57")).toBeInTheDocument();
    });

    it("hides the countdown once the scheduled start time has passed", async () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:59:58.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T15:00:00"
          gmtOffset="02:00:00"
        />
      );
      expect(screen.getByText("Starts In")).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(3000);

      expect(screen.queryByText("Starts In")).not.toBeInTheDocument();
    });

    it("doesn't double-append Z when StartDate already carries one", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T15:00:00Z"
          gmtOffset="02:00:00"
        />
      );

      // Already-UTC StartDate ("...15:00:00Z") minus the +02:00 offset -> 13:00:00Z,
      // i.e. 10 minutes from "now" - same as the equivalent non-Z-suffixed case above.
      expect(screen.getByText("0:10:00")).toBeInTheDocument();
    });

    it("treats StartDate as UTC directly when GmtOffset is absent", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T13:00:00"
        />
      );

      expect(screen.getByText("0:10:00")).toBeInTheDocument();
    });

    it("falls back to treating StartDate as UTC when GmtOffset is malformed", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T13:00:00"
          gmtOffset="not-an-offset"
        />
      );

      expect(screen.getByText("0:10:00")).toBeInTheDocument();
    });

    it("handles a negative GmtOffset", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T08:00:00"
          gmtOffset="-05:00:00"
        />
      );

      // Local 08:00:00 at UTC-5 -> UTC 13:00:00, i.e. 10 minutes from "now".
      expect(screen.getByText("0:10:00")).toBeInTheDocument();
    });

    it("ignores an unparseable StartDate", () => {
      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{}}
          isQualifying={false}
          qualifyingPart={null}
          startDate="not-a-date"
          gmtOffset="02:00:00"
        />
      );
      expect(screen.queryByText("Starts In")).not.toBeInTheDocument();
    });
  });

  describe("Paused indicator", () => {
    it(
      "shows Paused when Extrapolating is false mid-session - real scenario: F1 sets " +
        "Extrapolating: false the instant a red flag comes out",
      () => {
        render(
          <SessionClock
            lapCount={{ CurrentLap: 3 }}
            extrapolatedClock={{ Remaining: "01:55:48", Extrapolating: false }}
            isQualifying={false}
            qualifyingPart={null}
          />
        );
        expect(screen.getByText("Paused")).toBeInTheDocument();
      }
    );

    it("does not show Paused while the clock is actively ticking (Extrapolating: true)", () => {
      render(
        <SessionClock
          lapCount={{ CurrentLap: 3 }}
          extrapolatedClock={{ Remaining: "01:55:48", Extrapolating: true }}
          isQualifying={false}
          qualifyingPart={null}
        />
      );
      expect(screen.queryByText("Paused")).not.toBeInTheDocument();
    });

    it("does not show Paused before any Remaining value has arrived", () => {
      render(<SessionClock lapCount={{}} extrapolatedClock={{}} isQualifying={false} qualifyingPart={null} />);
      expect(screen.queryByText("Paused")).not.toBeInTheDocument();
    });

    it("does not show Paused before the session has started - Starts In already covers that case", () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-06T12:50:00.000Z"));

      render(
        <SessionClock
          lapCount={{}}
          extrapolatedClock={{ Remaining: "02:00:00", Extrapolating: false }}
          isQualifying={false}
          qualifyingPart={null}
          startDate="2026-09-06T15:00:00"
          gmtOffset="02:00:00"
        />
      );

      expect(screen.getByText("Starts In")).toBeInTheDocument();
      expect(screen.queryByText("Paused")).not.toBeInTheDocument();
    });
  });
});
