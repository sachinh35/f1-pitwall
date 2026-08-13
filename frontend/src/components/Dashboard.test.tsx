import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi, beforeEach } from "vitest";
import Dashboard from "./Dashboard";
import * as api from "../services/api";

vi.mock("../services/api", () => ({
    getYears: vi.fn().mockResolvedValue([]),
    getRacesForYear: vi.fn().mockResolvedValue([]),
    getSessionResults: vi.fn().mockResolvedValue([]),
    getSessionLapData: vi.fn().mockResolvedValue([]),
    getSessionStints: vi.fn().mockResolvedValue([]),
    getSessionRaceControlEvents: vi.fn().mockResolvedValue([]),
    startLiveStream: vi.fn(),
    startSimulation: vi.fn(),
    attachLiveStream: vi.fn(),
    getTeamDriverPool: vi.fn().mockResolvedValue({ season_year: 2026, drivers: [] }),
    getF1TvTokenStatus: vi.fn(),
    updateF1TvToken: vi.fn(),
}));

beforeEach(() => {
    vi.mocked(api.startLiveStream).mockReset();
    vi.mocked(api.startSimulation).mockReset();
    vi.mocked(api.getTeamDriverPool).mockReset();
    vi.mocked(api.getTeamDriverPool).mockResolvedValue({ season_year: 2026, drivers: [] });
    vi.mocked(api.getF1TvTokenStatus).mockReset();
    vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: true });
    vi.mocked(api.updateF1TvToken).mockReset();
});

describe("Dashboard start-stream wiring", () => {
    it("clicking 'Start Live Stream' opens the roster confirmation dialog instead of calling the API immediately", async () => {
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );

        fireEvent.click(screen.getByRole("button", { name: /start live stream/i }));

        await waitFor(() => expect(screen.getByText("Confirm Lineup Before Going Live")).toBeInTheDocument());
        expect(api.startLiveStream).not.toHaveBeenCalled();
    });

    it("clicking 'Test Simulation' opens the roster confirmation dialog instead of calling the API immediately", async () => {
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );

        fireEvent.click(screen.getByRole("button", { name: /test simulation/i }));

        await waitFor(() => expect(screen.getByText("Confirm Lineup for Simulation")).toBeInTheDocument());
        expect(api.startSimulation).not.toHaveBeenCalled();
    });
});

describe("Dashboard F1TV token gating on the live-stream path", () => {
    const singleDriverPool = {
        season_year: 2026,
        drivers: [
            { team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false },
        ],
    };

    const goLiveThroughRosterDialog = async () => {
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );

        fireEvent.click(screen.getByRole("button", { name: /start live stream/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));
    };

    beforeEach(() => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue(singleDriverPool);
        vi.mocked(api.startLiveStream).mockResolvedValue({
            success: true,
            message: "ok",
            stream_id: "stream-1",
            log_file: "stream_logs/stream-1.jsonl",
        });
    });

    it("a valid token status calls startLiveStream directly, without the token dialog appearing", async () => {
        vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: true });

        await goLiveThroughRosterDialog();

        await waitFor(() => expect(api.startLiveStream).toHaveBeenCalledTimes(1));
        expect(screen.queryByText("Update F1TV Token")).not.toBeInTheDocument();
    });

    it("an invalid token status opens the token dialog and blocks startLiveStream until onValidated fires", async () => {
        vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: false, reason: "Token has expired" });
        vi.mocked(api.updateF1TvToken).mockResolvedValue({ valid: true });

        await goLiveThroughRosterDialog();

        await waitFor(() => expect(screen.getByText("Update F1TV Token")).toBeInTheDocument());
        expect(screen.getByText("Token has expired", { exact: false })).toBeInTheDocument();
        expect(api.startLiveStream).not.toHaveBeenCalled();

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "fresh.jwt.token" } });
        fireEvent.click(screen.getByRole("button", { name: "I've updated the token" }));

        await waitFor(() => expect(api.startLiveStream).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(screen.queryByText("Update F1TV Token")).not.toBeInTheDocument());
    });
});
