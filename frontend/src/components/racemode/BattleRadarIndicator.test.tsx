import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BattleRadarIndicator from "./BattleRadarIndicator";
import { BattleRadarAlert } from "../../types/raceMode";

const baseAlert: BattleRadarAlert = {
  driver_number: 44,
  ahead_driver_number: 16,
  gap_seconds: 1.05,
  alert_level: "battle",
  lap_history: [
    { lap_number: 12, gap_seconds: 1.8 },
    { lap_number: 13, gap_seconds: 1.4 },
    { lap_number: 14, gap_seconds: 1.05 },
  ],
};

describe("BattleRadarIndicator", () => {
  it("renders nothing when alert is undefined", () => {
    const { container } = render(<BattleRadarIndicator alert={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a visually-distinct badge for battle vs upcoming alert levels", () => {
    const { container: battleContainer } = render(<BattleRadarIndicator alert={baseAlert} />);
    const battleBadge = battleContainer.querySelector(".battle-radar-badge");
    expect(battleBadge).not.toBeNull();
    expect(battleBadge?.className).toContain("battle-radar-battle");

    const upcomingAlert: BattleRadarAlert = { ...baseAlert, alert_level: "upcoming" };
    const { container: upcomingContainer } = render(<BattleRadarIndicator alert={upcomingAlert} />);
    const upcomingBadge = upcomingContainer.querySelector(".battle-radar-badge");
    expect(upcomingBadge).not.toBeNull();
    expect(upcomingBadge?.className).toContain("battle-radar-upcoming");

    expect(battleBadge?.className).not.toEqual(upcomingBadge?.className);
  });

  it("shows the popover with gap and chase target on hover", () => {
    render(<BattleRadarIndicator alert={baseAlert} />);
    const badge = screen.getByTitle(/battle imminent/i);

    expect(screen.queryByText(/1\.05s/)).not.toBeInTheDocument();

    fireEvent.mouseEnter(badge);

    expect(screen.getByText(/closing on lec/i)).toBeInTheDocument();
    expect(screen.getByText("1.05s")).toBeInTheDocument();
    // recharts renders a real svg chart container once the popover is open
    expect(document.querySelector(".recharts-wrapper")).not.toBeNull();
  });

  it("uses the amber (not red) chart line color for an upcoming (not yet imminent) battle", () => {
    const upcomingAlert: BattleRadarAlert = { ...baseAlert, alert_level: "upcoming" };
    render(<BattleRadarIndicator alert={upcomingAlert} />);
    fireEvent.mouseEnter(screen.getByTitle(/battle forming/i));
    expect(document.querySelector(".recharts-line-curve")).toHaveAttribute("stroke", "var(--amber)");
  });

  it("hides the popover again on mouse leave", () => {
    render(<BattleRadarIndicator alert={baseAlert} />);
    const badge = screen.getByTitle(/battle imminent/i);

    fireEvent.mouseEnter(badge);
    expect(screen.getByText("1.05s")).toBeInTheDocument();

    fireEvent.mouseLeave(badge);
    expect(screen.queryByText("1.05s")).not.toBeInTheDocument();
  });

  it("shows the popover on keyboard focus as well as hover", () => {
    render(<BattleRadarIndicator alert={baseAlert} />);
    const badge = screen.getByTitle(/battle imminent/i);

    fireEvent.focus(badge);
    expect(screen.getByText("1.05s")).toBeInTheDocument();

    fireEvent.blur(badge);
    expect(screen.queryByText("1.05s")).not.toBeInTheDocument();
  });

  it("handles a null ahead_driver_number gracefully, without a nonsensical closing-on string", () => {
    const alertWithNoAhead: BattleRadarAlert = { ...baseAlert, ahead_driver_number: null };
    render(<BattleRadarIndicator alert={alertWithNoAhead} />);
    const badge = screen.getByTitle(/battle imminent/i);

    fireEvent.mouseEnter(badge);

    expect(screen.queryByText(/closing on/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
    expect(screen.getByText("1.05s")).toBeInTheDocument();
  });
});
