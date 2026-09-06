import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TrackStatusFlag from "./TrackStatusFlag";

describe("TrackStatusFlag", () => {
  it("renders the real flag message text from the feed", () => {
    render(<TrackStatusFlag trackStatus={{ Status: "4", Message: "Red Flag" }} />);
    expect(screen.getByText("Red Flag")).toBeInTheDocument();
  });

  it("shows Unknown before any track status has arrived", () => {
    render(<TrackStatusFlag trackStatus={{}} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("applies the red status class for a red flag", () => {
    const { container } = render(<TrackStatusFlag trackStatus={{ Status: "4", Message: "Red Flag" }} />);
    expect(container.querySelector(".status-red")).not.toBeNull();
  });

  it("applies the yellow status class for a safety car deployment", () => {
    const { container } = render(<TrackStatusFlag trackStatus={{ Status: "6", Message: "SC Deployed" }} />);
    expect(container.querySelector(".status-yellow")).not.toBeNull();
  });

  it("renders as the compact top-banner variant", () => {
    const { container } = render(<TrackStatusFlag trackStatus={{ Status: "1", Message: "AllClear" }} />);
    expect(container.querySelector(".flag-banner-top")).not.toBeNull();
  });

  it("shows Race Suspended (in red) when the session is Aborted, even if TrackStatus looks clear", () => {
    const { container } = render(
      <TrackStatusFlag trackStatus={{ Status: "2", Message: "Yellow" }} sessionStatus={{ Status: "Aborted" }} />
    );
    expect(screen.getByText("Race Suspended")).toBeInTheDocument();
    expect(container.querySelector(".status-red")).not.toBeNull();
  });
});
