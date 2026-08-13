import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TrackStatusBanner from "./TrackStatusBanner";

describe("TrackStatusBanner", () => {
  it("renders the real flag message text from the feed", () => {
    render(<TrackStatusBanner trackStatus={{ Status: "2", Message: "Yellow" }} weather={{}} />);
    expect(screen.getByText("Yellow")).toBeInTheDocument();
  });

  it("shows Unknown before any track status has arrived", () => {
    render(<TrackStatusBanner trackStatus={{}} weather={{}} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("renders real weather figures", () => {
    render(<TrackStatusBanner trackStatus={{}} weather={{ AirTemp: "25.1", TrackTemp: "30.8", Humidity: "50.0" }} />);
    expect(screen.getByText("30.8°")).toBeInTheDocument();
    expect(screen.getByText("25.1°")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
  });

  it("shows Wet only when Rainfall is exactly \"1\"", () => {
    const { rerender } = render(<TrackStatusBanner trackStatus={{}} weather={{ Rainfall: "0" }} />);
    expect(screen.getByText("Dry")).toBeInTheDocument();

    rerender(<TrackStatusBanner trackStatus={{}} weather={{ Rainfall: "1" }} />);
    expect(screen.getByText("Wet")).toBeInTheDocument();
  });
});
