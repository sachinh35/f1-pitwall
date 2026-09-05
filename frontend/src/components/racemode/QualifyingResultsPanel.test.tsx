import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QualifyingResultsPanel from "./QualifyingResultsPanel";
import { QualifyingResultEntry } from "../../services/api";

function entry(overrides: Partial<QualifyingResultEntry> = {}): QualifyingResultEntry {
  return { driver_number: 1, position: 1, best_lap_seconds: 80.5, gap_to_leader_seconds: 0, eliminated: false, ...overrides };
}

describe("QualifyingResultsPanel", () => {
  it("renders nothing when no segment has finished yet", () => {
    const { container } = render(<QualifyingResultsPanel results={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a segment key present but with an empty entry list", () => {
    const { container } = render(<QualifyingResultsPanel results={{ Q1: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one card per finished segment, in Q1/Q2/Q3 order", () => {
    render(
      <QualifyingResultsPanel
        results={{
          Q2: [entry({ driver_number: 1 })],
          Q1: [entry({ driver_number: 1 })],
        }}
      />
    );
    const summaries = screen.getAllByText(/Results$/);
    expect(summaries.map((el) => el.textContent)).toEqual(["Q1 Results", "Q2 Results"]);
  });

  it("shows the driver count in each card's summary", () => {
    render(
      <QualifyingResultsPanel
        results={{ Q1: [entry({ driver_number: 1 }), entry({ driver_number: 2, position: 2 })] }}
      />
    );
    expect(screen.getByText("2 drivers")).toBeInTheDocument();
  });

  it("sorts entries by position, not insertion order", () => {
    render(
      <QualifyingResultsPanel
        results={{
          Q1: [
            entry({ driver_number: 44, position: 2 }),
            entry({ driver_number: 1, position: 1 }),
          ],
        }}
      />
    );
    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows[0]).toHaveTextContent("1");
    expect(rows[1]).toHaveTextContent("2");
  });

  it("sorts an entry with no known position last", () => {
    render(
      <QualifyingResultsPanel
        results={{
          Q1: [
            entry({ driver_number: 1, position: null }),
            entry({ driver_number: 44, position: 1 }),
          ],
        }}
      />
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("1");
    expect(rows[1]).toHaveTextContent("-");
  });

  it("formats a valid best lap time", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ best_lap_seconds: 82.612 })] }} />);
    expect(screen.getByText("1:22.612")).toBeInTheDocument();
  });

  it("shows a dash for a missing best lap time", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ best_lap_seconds: null })] }} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.some((c) => c.textContent === "-")).toBe(true);
  });

  it("shows a dash for a missing gap", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ gap_to_leader_seconds: null })] }} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.some((c) => c.textContent === "-")).toBe(true);
  });

  it("keeps entries with no known position in a stable relative order", () => {
    render(
      <QualifyingResultsPanel
        results={{
          Q1: [
            entry({ driver_number: 1, position: null }),
            entry({ driver_number: 44, position: null }),
          ],
        }}
      />
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
  });

  it("shows 'Leader' for a gap of exactly zero", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ gap_to_leader_seconds: 0 })] }} />);
    expect(screen.getByText("Leader")).toBeInTheDocument();
  });

  it("formats a nonzero gap with a leading plus sign", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ gap_to_leader_seconds: 0.347 })] }} />);
    expect(screen.getByText("+0.347")).toBeInTheDocument();
  });

  it("marks an eliminated driver's row", () => {
    render(<QualifyingResultsPanel results={{ Q1: [entry({ eliminated: true })] }} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveClass("eliminated");
  });
});
