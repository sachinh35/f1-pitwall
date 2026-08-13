import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TyreStrategyPredictionWire } from "../../types/raceMode";
import TyreStintIndicator from "./TyreStintIndicator";

const SAMPLE_PREDICTION: TyreStrategyPredictionWire = {
  driver_number: 44,
  generated_at_lap: 25,
  predicted_stints: [
    { stint_number: 1, compound: "hard", predicted_total_laps: 30 },
    { stint_number: 2, compound: "medium", predicted_total_laps: 40 },
  ],
  safety_car_note: "Low historical safety car risk at this circuit.",
  summary: "One more stop, likely onto medium around lap 30.",
};

describe("TyreStintIndicator", () => {
  it("renders an unknown chip and no popover trigger when there are no stints", () => {
    render(<TyreStintIndicator stints={[]} />);
    expect(screen.getByText("?")).toBeInTheDocument();
    expect(document.querySelector(".tyre-stint-badge")).toBeNull();
  });

  it("renders one chip per stint, including repeated compounds", () => {
    render(
      <TyreStintIndicator
        stints={[
          { compound: "soft", laps: 13 },
          { compound: "hard", laps: 17 },
          { compound: "hard", laps: 4 },
        ]}
      />
    );
    expect(screen.getAllByText("H")).toHaveLength(2);
    expect(screen.getAllByText("S")).toHaveLength(1);
  });

  it("marks only the last stint as current", () => {
    render(
      <TyreStintIndicator
        stints={[
          { compound: "soft", laps: 13 },
          { compound: "hard", laps: 4 },
        ]}
      />
    );
    const chips = document.querySelectorAll(".tyre-chip-mini");
    expect(chips[0].className).not.toContain("current");
    expect(chips[1].className).toContain("current");
  });

  it("shows the popover with a segment per stint and its lap count on hover", () => {
    render(
      <TyreStintIndicator
        stints={[
          { compound: "soft", laps: 13 },
          { compound: "hard", laps: 17 },
        ]}
      />
    );
    fireEvent.mouseEnter(document.querySelector(".tyre-stint-badge")!);
    const segments = document.querySelectorAll(".tyre-stint-segment");
    expect(segments).toHaveLength(2);
    expect(segments[0].className).toContain("soft");
    expect(segments[1].className).toContain("hard");
    expect(screen.getByText("13L")).toBeInTheDocument();
    expect(screen.getByText("17L")).toBeInTheDocument();
  });

  it("shows a '?' lap label when a stint has no lap count yet", () => {
    render(<TyreStintIndicator stints={[{ compound: "medium" }]} />);
    fireEvent.mouseEnter(document.querySelector(".tyre-stint-badge")!);
    const segment = document.querySelector(".tyre-stint-segment");
    expect(segment?.textContent).toContain("?");
  });

  it("opens on focus and closes on blur (keyboard accessibility)", () => {
    render(<TyreStintIndicator stints={[{ compound: "soft", laps: 5 }]} />);
    const badge = document.querySelector(".tyre-stint-badge")!;
    fireEvent.focus(badge);
    expect(screen.getByText("Tyre Strategy")).toBeInTheDocument();
    fireEvent.blur(badge);
    expect(screen.queryByText("Tyre Strategy")).not.toBeInTheDocument();
  });

  describe("predicted strategy", () => {
    it("does not render a predicted section when there is no prediction yet", () => {
      render(<TyreStintIndicator stints={[{ compound: "soft", laps: 5 }]} />);
      fireEvent.mouseEnter(document.querySelector(".tyre-stint-badge")!);
      expect(screen.queryByText("Predicted Strategy")).not.toBeInTheDocument();
    });

    it("shows a predicted strategy bar with one segment per predicted stint on hover", () => {
      render(
        <TyreStintIndicator stints={[{ compound: "hard", laps: 8 }]} prediction={SAMPLE_PREDICTION} />
      );
      fireEvent.mouseEnter(document.querySelector(".tyre-stint-badge")!);

      expect(screen.getByText("Predicted Strategy")).toBeInTheDocument();
      const predictedSegments = document.querySelectorAll(".tyre-stint-segment.predicted");
      expect(predictedSegments).toHaveLength(2);
      expect(predictedSegments[0].className).toContain("hard");
      expect(predictedSegments[1].className).toContain("medium");
      expect(screen.getByText("30L")).toBeInTheDocument();
      expect(screen.getByText("40L")).toBeInTheDocument();
    });

    it("shows the model's summary, safety car note, and generation lap", () => {
      render(
        <TyreStintIndicator stints={[{ compound: "hard", laps: 8 }]} prediction={SAMPLE_PREDICTION} />
      );
      fireEvent.mouseEnter(document.querySelector(".tyre-stint-badge")!);

      expect(screen.getByText("One more stop, likely onto medium around lap 30.")).toBeInTheDocument();
      expect(screen.getByText("Low historical safety car risk at this circuit.")).toBeInTheDocument();
      expect(screen.getByText("as of lap 25")).toBeInTheDocument();
    });

    it("hides the predicted section again once the popover closes", () => {
      render(
        <TyreStintIndicator stints={[{ compound: "hard", laps: 8 }]} prediction={SAMPLE_PREDICTION} />
      );
      const badge = document.querySelector(".tyre-stint-badge")!;
      fireEvent.mouseEnter(badge);
      expect(screen.getByText("Predicted Strategy")).toBeInTheDocument();
      fireEvent.mouseLeave(badge);
      expect(screen.queryByText("Predicted Strategy")).not.toBeInTheDocument();
    });
  });
});
