import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LapDeltaChart from "./LapDeltaChart";
import { getLapComparison } from "../../services/api";
import { DriverTiming, LapComparisonData } from "../../types/raceMode";

vi.mock("../../services/api", () => ({
  getLapComparison: vi.fn(),
}));

const mockedGetLapComparison = vi.mocked(getLapComparison);

function buildComparison(overrides: Partial<LapComparisonData> = {}): LapComparisonData {
  return {
    session_key: 9850,
    driver_a: {
      driver_number: 1,
      lap_number: 5,
      distance_m: [0, 100, 200],
      speed_kmh: [250, 280, 300],
      throttle_pct: [100, 100, 100],
      brake_pct: [0, 0, 0],
      acceleration_ms2: [1, 0.5, 0],
    },
    driver_b: {
      driver_number: 44,
      lap_number: 5,
      distance_m: [0, 100, 200],
      speed_kmh: [245, 275, 298],
      throttle_pct: [100, 100, 100],
      brake_pct: [0, 0, 0],
      acceleration_ms2: [1, 0.4, 0],
    },
    delta: {
      distance_m: [0, 100, 200],
      delta_seconds: [0, 0.05, -0.1],
      corners: [{ distance_m: 100, apex_speed_kmh: 180 }],
    },
    ...overrides,
  };
}

const driverTimings: Record<string, DriverTiming> = {
  "1": { NumberOfLaps: 5 } as DriverTiming,
  "44": { NumberOfLaps: 6 } as DriverTiming,
};

beforeEach(() => {
  mockedGetLapComparison.mockReset();
});

describe("LapDeltaChart", () => {
  it("prompts for a second driver when fewer than 2 are selected", () => {
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1]} drivers={driverTimings} />);
    expect(screen.getByText(/Select 2 drivers/)).toBeInTheDocument();
  });

  it("prompts for drivers when none are selected", () => {
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[]} drivers={driverTimings} />);
    expect(screen.getByText(/Select 2 drivers/)).toBeInTheDocument();
  });

  it("defaults each driver's lap input to their most recently completed lap", () => {
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);
    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(inputs[0].value).toBe("4"); // NumberOfLaps 5 - 1
    expect(inputs[1].value).toBe("5"); // NumberOfLaps 6 - 1
  });

  it("defaults to lap 1 when a driver has no known completed lap yet", () => {
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={{}} />);
    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(inputs[0].value).toBe("1");
    expect(inputs[1].value).toBe("1");
  });

  it("disables Compare until a session key and both lap numbers are known", () => {
    render(<LapDeltaChart sessionKey={null} selectedDrivers={[1, 44]} drivers={driverTimings} />);
    expect(screen.getByRole("button", { name: /Compare/ })).toBeDisabled();
  });

  it("fetches and renders a comparison on Compare", async () => {
    mockedGetLapComparison.mockResolvedValue(buildComparison());
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    await waitFor(() => expect(mockedGetLapComparison).toHaveBeenCalledWith(9850, 1, 4, 44, 5));
    expect(await screen.findByText(/relative to/)).toBeInTheDocument();
  });

  it("reports the trailing driver losing time when the final delta is positive", async () => {
    mockedGetLapComparison.mockResolvedValue(buildComparison({ delta: { distance_m: [0, 100], delta_seconds: [0, 0.25], corners: [] } }));
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    expect(await screen.findByText(/lost/)).toBeInTheDocument();
    expect(screen.getByText("0.250s")).toBeInTheDocument();
  });

  it("reports the trailing driver gaining time when the final delta is negative", async () => {
    mockedGetLapComparison.mockResolvedValue(buildComparison({ delta: { distance_m: [0, 100], delta_seconds: [0, -0.18], corners: [] } }));
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    expect(await screen.findByText(/gained/)).toBeInTheDocument();
  });

  it("shows an error and no chart when the comparison fetch fails", async () => {
    mockedGetLapComparison.mockRejectedValue(new Error("boom"));
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    expect(await screen.findByText(/No data for that lap pairing yet/)).toBeInTheDocument();
    expect(screen.queryByText(/detected corners/)).not.toBeInTheDocument();
  });

  it("lets the user override a lap number before comparing", async () => {
    mockedGetLapComparison.mockResolvedValue(buildComparison());
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "2" } });
    fireEvent.change(inputs[1], { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    await waitFor(() => expect(mockedGetLapComparison).toHaveBeenCalledWith(9850, 1, 2, 44, 3));
  });

  it("draws the delta chart without dividing by zero when every distance sample is 0", async () => {
    mockedGetLapComparison.mockResolvedValue(
      buildComparison({ delta: { distance_m: [0, 0], delta_seconds: [0, 0.05], corners: [] } })
    );
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    expect(() => fireEvent.click(screen.getByRole("button", { name: /Compare/ }))).not.toThrow();
    await screen.findByText("Speed vs. Distance");
  });

  it("draws the speed/acceleration traces without dividing by zero when every sample is identical", async () => {
    const flatTrace = {
      driver_number: 1,
      lap_number: 5,
      distance_m: [0, 0, 0],
      speed_kmh: [280, 280, 280],
      throttle_pct: [100, 100, 100],
      brake_pct: [0, 0, 0],
      acceleration_ms2: [0, 0, 0],
    };
    mockedGetLapComparison.mockResolvedValue(buildComparison({ driver_a: flatTrace, driver_b: flatTrace }));
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    expect(() => fireEvent.click(screen.getByRole("button", { name: /Compare/ }))).not.toThrow();
    await screen.findByText("Speed vs. Distance");
  });

  it("does not render a summary line when the delta series is empty", async () => {
    mockedGetLapComparison.mockResolvedValue(buildComparison({ delta: { distance_m: [], delta_seconds: [], corners: [] } }));
    render(<LapDeltaChart sessionKey={9850} selectedDrivers={[1, 44]} drivers={driverTimings} />);

    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));

    await screen.findByText("Speed vs. Distance");
    expect(screen.queryByText(/relative to/)).not.toBeInTheDocument();
  });
});
