import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi, beforeEach } from "vitest";
import Dashboard from "./Dashboard";
import * as api from "../services/api";
import { Race, EnrichedF1SessionResult } from "../types";

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

    it("shows an auth-specific error message when the token status check itself fails", async () => {
        vi.mocked(api.getF1TvTokenStatus).mockRejectedValue(new Error("network down"));

        await goLiveThroughRosterDialog();

        await waitFor(() =>
            expect(screen.getByText(/failed to check f1tv token status/i)).toBeInTheDocument()
        );
        expect(api.startLiveStream).not.toHaveBeenCalled();
    });

    it("falls back to a generic reason in the token dialog when the status response gives none", async () => {
        vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: false });

        await goLiveThroughRosterDialog();

        await waitFor(() => expect(screen.getByText("Update F1TV Token")).toBeInTheDocument());
        expect(screen.getByText(/your f1tv token is missing or expired/i)).toBeInTheDocument();
    });
});

describe("Dashboard start-live-stream error handling", () => {
    const singleDriverPool = {
        season_year: 2026,
        drivers: [
            { team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false },
        ],
    };

    beforeEach(() => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue(singleDriverPool);
        vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: true });
    });

    const goLive = async () => {
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /start live stream/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));
    };

    it("shows the F1TV-auth-specific message on a 401 response", async () => {
        const axiosError = Object.assign(new Error("Unauthorized"), {
            isAxiosError: true,
            response: { status: 401, data: {} },
        });
        vi.mocked(api.startLiveStream).mockRejectedValue(axiosError);

        await goLive();

        await waitFor(() => expect(screen.getByText(/authentication required/i)).toBeInTheDocument());
    });

    it("shows the backend-provided detail message when present on a non-auth error response", async () => {
        const axiosError = Object.assign(new Error("Bad Request"), {
            isAxiosError: true,
            response: { status: 500, data: { detail: "Stream already running" } },
        });
        vi.mocked(api.startLiveStream).mockRejectedValue(axiosError);

        await goLive();

        await waitFor(() => expect(screen.getByText("Stream already running")).toBeInTheDocument());
    });

    it("shows a generic fallback message for a non-axios error", async () => {
        vi.mocked(api.startLiveStream).mockRejectedValue(new Error("boom"));

        await goLive();

        await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    });

    it("keeps the generic fallback message for an axios error with neither an auth status nor a detail field", async () => {
        const axiosError = Object.assign(new Error("Server Error"), {
            isAxiosError: true,
            response: { status: 500, data: {} },
        });
        vi.mocked(api.startLiveStream).mockRejectedValue(axiosError);

        await goLive();

        await waitFor(() => expect(screen.getByText("Failed to start live stream.")).toBeInTheDocument());
    });

    it("keeps the generic fallback message for a thrown non-Error value", async () => {
        vi.mocked(api.startLiveStream).mockRejectedValue("a plain string rejection");

        await goLive();

        await waitFor(() => expect(screen.getByText("Failed to start live stream.")).toBeInTheDocument());
    });

    it("closing the error snackbar clears the message", async () => {
        vi.mocked(api.startLiveStream).mockRejectedValue(new Error("boom"));

        await goLive();

        await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
        fireEvent.click(screen.getByLabelText(/close/i));
        await waitFor(() => expect(screen.queryByText("boom")).not.toBeInTheDocument());
    });
});

describe("Dashboard simulation and attach-to-live-capture flows", () => {
    const singleDriverPool = {
        season_year: 2026,
        drivers: [
            { team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false },
        ],
    };

    beforeEach(() => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue(singleDriverPool);
    });

    it("starting a simulation navigates to the new stream's live page", async () => {
        vi.mocked(api.startSimulation).mockResolvedValue({
            success: true,
            message: "ok",
            stream_id: "sim-1",
            log_file: "stream_logs/sim-1.jsonl",
        });

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /test simulation/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(api.startSimulation).toHaveBeenCalledTimes(1));
    });

    it("shows an error message when starting a simulation fails", async () => {
        vi.mocked(api.startSimulation).mockRejectedValue(new Error("boom"));

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /test simulation/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText("Failed to start simulation")).toBeInTheDocument());
    });

    it("attaching to a live capture succeeds and navigates to the stream page", async () => {
        vi.mocked(api.attachLiveStream).mockResolvedValue({
            success: true,
            message: "ok",
            stream_id: "attach-1",
            log_file: "stream_logs/attach-1.jsonl",
        });

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /attach to live capture/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() =>
            expect(screen.getByText(/attached to live capture/i)).toBeInTheDocument()
        );
    });

    it("shows a not-found-specific message when attaching to a live capture 404s", async () => {
        const axiosError = Object.assign(new Error("Not Found"), {
            isAxiosError: true,
            response: { status: 404, data: {} },
        });
        vi.mocked(api.attachLiveStream).mockRejectedValue(axiosError);

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /attach to live capture/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText(/no live capture found/i)).toBeInTheDocument());
    });

    it("shows a generic fallback message for a non-axios attach error", async () => {
        vi.mocked(api.attachLiveStream).mockRejectedValue(new Error("boom"));

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /attach to live capture/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    });

    it("keeps the generic fallback message for a thrown non-Error value while attaching", async () => {
        vi.mocked(api.attachLiveStream).mockRejectedValue("a plain string rejection");

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /attach to live capture/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText("Failed to attach to live capture.")).toBeInTheDocument());
    });
});

describe("Dashboard season/location/session selection and results table", () => {
    const races: Race[] = [
        { session_key: 1, location: "Silverstone", session_name: "Race", country_code: "GBR" },
        { session_key: 2, location: "Silverstone", session_name: "Qualifying", country_code: "GBR" },
        { session_key: 3, location: "Monza", session_name: "Race", country_code: "ITA" },
    ];

    const results: EnrichedF1SessionResult[] = [
        {
            dnf: false, dns: false, dsq: false, driver_number: 1, number_of_laps: 52,
            meeting_key: 1, session_key: 1, duration: 5400, gap_to_leader: null, position: 1,
            full_name: "Lando Norris", name_acronym: "NOR", first_name: "Lando", last_name: "Norris",
            country_code: "GBR",
        },
        {
            dnf: true, dns: false, dsq: false, driver_number: 3, number_of_laps: 30,
            meeting_key: 1, session_key: 1, duration: null, gap_to_leader: null, position: null,
            full_name: "Max Verstappen", name_acronym: "VER", first_name: "Max", last_name: "Verstappen",
            country_code: null,
        },
        {
            dnf: false, dns: true, dsq: true, driver_number: 16, number_of_laps: null,
            meeting_key: 1, session_key: 1, duration: 5450, gap_to_leader: 50, position: 3,
            full_name: "Charles Leclerc", name_acronym: "LEC", first_name: "Charles", last_name: "Leclerc",
            country_code: "MON",
        },
    ];

    beforeEach(() => {
        // Reset (not just re-stub) each mock - a prior test's mockResolvedValueOnce/
        // mockRejectedValueOnce would otherwise still be queued up ahead of this base
        // implementation and leak into the next test.
        vi.mocked(api.getYears).mockReset().mockResolvedValue([2026, 2025]);
        vi.mocked(api.getRacesForYear).mockReset().mockResolvedValue(races);
        vi.mocked(api.getSessionResults).mockReset().mockResolvedValue(results);
        vi.mocked(api.getSessionLapData).mockReset().mockResolvedValue([]);
        vi.mocked(api.getSessionStints).mockReset().mockResolvedValue([]);
        vi.mocked(api.getSessionRaceControlEvents).mockReset().mockResolvedValue([]);
    });

    const selectSession = async () => {
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );

        fireEvent.mouseDown(screen.getByText("Select a season..."));
        fireEvent.click(await screen.findByRole("option", { name: "2026" }));

        fireEvent.mouseDown(await screen.findByText("Select a location..."));
        fireEvent.click(await screen.findByRole("option", { name: /Silverstone/ }));

        fireEvent.mouseDown(await screen.findByText("Select a session..."));
        fireEvent.click(await screen.findByRole("option", { name: "Race" }));

        await waitFor(() => expect(screen.getByText("Session Results")).toBeInTheDocument());
    };

    it("cascades year -> location -> session and renders the results table with DNF/DNS/DSQ chips", async () => {
        await selectSession();

        expect(screen.getByText("Lando Norris")).toBeInTheDocument();
        expect(screen.getByText("DNF", { selector: ".MuiChip-label" })).toBeInTheDocument();
        expect(screen.getByText("DNS", { selector: ".MuiChip-label" })).toBeInTheDocument();
        expect(screen.getByText("DSQ", { selector: ".MuiChip-label" })).toBeInTheDocument();
        expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    });

    it("renders a location option with no flag emoji when the race has no country_code", async () => {
        vi.mocked(api.getRacesForYear).mockResolvedValue([
            ...races,
            { session_key: 4, location: "Unknown Circuit", session_name: "Race", country_code: "" },
        ]);
        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.mouseDown(screen.getByText("Select a season..."));
        fireEvent.click(await screen.findByRole("option", { name: "2026" }));
        fireEvent.mouseDown(await screen.findByText("Select a location..."));

        const option = await screen.findByRole("option", { name: "Unknown Circuit" });
        expect(option.textContent).toBe("Unknown Circuit"); // no leading flag emoji
    });

    it("uses the red position-1 chip styling for a non-leading displayed row whose actual position is 1", async () => {
        vi.mocked(api.getSessionResults).mockResolvedValue([
            results[1], // Max Verstappen, position: null -> shown first (index 0) this time
            { ...results[0], position: 1 }, // Lando Norris at index 1, but position 1
        ]);

        await selectSession();

        const bodyRows = document.querySelectorAll("tbody tr");
        // Second displayed row (index !== 0) whose actual `position` field is still 1 - takes
        // the dedicated (non-leader-row) red position-1 chip style, not the plain default.
        const positionChip = bodyRows[1].querySelector("td:first-child .MuiChip-root");
        expect(positionChip).toHaveStyle({ backgroundColor: "rgba(225, 6, 0, 0.3)" });
    });

    it("resets the location/session selection when the season changes", async () => {
        await selectSession();
        expect(screen.getByText("Session Results")).toBeInTheDocument();

        // Changing the season back to the same list clears the previously-selected
        // location/session and the results table along with it.
        const seasonSelect = screen.getAllByRole("combobox")[0];
        fireEvent.mouseDown(seasonSelect);
        fireEvent.click(await screen.findByRole("option", { name: "2025" }));

        await waitFor(() => expect(screen.queryByText("Session Results")).not.toBeInTheDocument());
    });

    it("toggles the Laps column off via the settings menu", async () => {
        await selectSession();
        expect(screen.getByRole("columnheader", { name: "Laps" })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "" }));
        const lapsCheckbox = await screen.findByRole("checkbox", { name: "Laps" });
        fireEvent.click(lapsCheckbox);

        await waitFor(() => expect(screen.queryByRole("columnheader", { name: "Laps" })).not.toBeInTheDocument());
    });

    it("shows a loading spinner while re-fetching results for a newly selected session (results card stays mounted from the prior session)", async () => {
        // The results Card - and its loading spinner - is only rendered while
        // sessionResults.length > 0, so the spinner is only observable on a *second*
        // selection while the previous session's results are still in state.
        await selectSession();
        expect(screen.getByText("Session Results")).toBeInTheDocument();

        let resolveResults!: (value: EnrichedF1SessionResult[]) => void;
        vi.mocked(api.getSessionResults).mockReturnValue(
            new Promise((resolve) => {
                resolveResults = resolve;
            })
        );

        const sessionSelect = screen.getAllByRole("combobox")[2];
        fireEvent.mouseDown(sessionSelect);
        fireEvent.click(await screen.findByRole("option", { name: "Qualifying" }));

        expect(screen.getByRole("progressbar")).toBeInTheDocument();
        resolveResults(results);
        await waitFor(() => expect(screen.queryByRole("progressbar")).not.toBeInTheDocument());
    });

    it("selecting a driver fetches and renders the lap comparison chart, replacing the placeholder prompts", async () => {
        vi.mocked(api.getSessionLapData).mockResolvedValue([
            {
                meeting_key: 1, session_key: 1, driver_number: 1, lap_number: 1, date_start: null,
                duration_sector_1: null, duration_sector_2: null, duration_sector_3: null, lap_duration: 90,
                i1_speed: null, i2_speed: null, st_speed: null, is_pit_out_lap: false,
                segments_sector_1: null, segments_sector_2: null,
            },
        ]);

        await selectSession();

        expect(screen.getByText(/select drivers above to compare lap times/i)).toBeInTheDocument();

        fireEvent.click(screen.getByRole("checkbox", { name: /Lando Norris/ }));

        await waitFor(() => expect(api.getSessionLapData).toHaveBeenCalledWith(1, [1]));
        await waitFor(() =>
            expect(screen.queryByText(/select drivers above to compare lap times/i)).not.toBeInTheDocument()
        );
    });

    it("does not re-fetch a driver that's already cached with data once another driver is also selected, and skips fetching entirely once the only remaining selection is fully cached", async () => {
        vi.mocked(api.getSessionLapData).mockImplementation(async (_key, driverNumbers) => [
            {
                meeting_key: 1, session_key: 1, driver_number: driverNumbers[0], lap_number: 1, date_start: null,
                duration_sector_1: null, duration_sector_2: null, duration_sector_3: null, lap_duration: 90,
                i1_speed: null, i2_speed: null, st_speed: null, is_pit_out_lap: false,
                segments_sector_1: null, segments_sector_2: null,
            },
        ]);

        await selectSession();
        fireEvent.click(screen.getByRole("checkbox", { name: /Lando Norris/ }));
        await waitFor(() => expect(api.getSessionLapData).toHaveBeenCalledTimes(1));

        // Selecting a second driver while the first stays selected - the first is already
        // cached with data in state, so only the second should be fetched.
        fireEvent.click(screen.getByRole("checkbox", { name: /Max Verstappen/ }));
        await waitFor(() => expect(api.getSessionLapData).toHaveBeenCalledTimes(2));
        expect(api.getSessionLapData).toHaveBeenLastCalledWith(1, [3]);

        // Deselecting the second driver leaves only the first, already-cached driver selected -
        // nothing left to fetch at all.
        fireEvent.click(screen.getByRole("checkbox", { name: /Max Verstappen/ }));
        await waitFor(() => expect(screen.queryByText(/select drivers above to compare lap times/i)).not.toBeInTheDocument());
        expect(api.getSessionLapData).toHaveBeenCalledTimes(2); // no 3rd call
    });

    it("shows a no-data message when a selected driver has no lap data available", async () => {
        vi.mocked(api.getSessionLapData).mockResolvedValue([]);

        await selectSession();
        fireEvent.click(screen.getByRole("checkbox", { name: /Lando Norris/ }));

        await waitFor(() =>
            expect(screen.getByText(/no lap data available for selected drivers/i)).toBeInTheDocument()
        );
    });

    it("falls back to empty stints/race-control-events (rather than crashing) when either fetch fails", async () => {
        vi.mocked(api.getSessionStints).mockRejectedValue(new Error("stints down"));
        vi.mocked(api.getSessionRaceControlEvents).mockRejectedValue(new Error("rc events down"));

        await expect(selectSession()).resolves.not.toThrow();
        expect(screen.getByText("Session Results")).toBeInTheDocument();
    });

    it("deselecting a driver removes their column from the lap comparison chart data", async () => {
        vi.mocked(api.getSessionLapData).mockResolvedValue([
            {
                meeting_key: 1, session_key: 1, driver_number: 1, lap_number: 1, date_start: null,
                duration_sector_1: null, duration_sector_2: null, duration_sector_3: null, lap_duration: 90,
                i1_speed: null, i2_speed: null, st_speed: null, is_pit_out_lap: false,
                segments_sector_1: null, segments_sector_2: null,
            },
        ]);

        await selectSession();
        const checkbox = screen.getByRole("checkbox", { name: /Lando Norris/ });
        fireEvent.click(checkbox);
        await waitFor(() => expect(api.getSessionLapData).toHaveBeenCalledTimes(1));

        fireEvent.click(checkbox);
        await waitFor(() => expect(screen.getByText(/select drivers above to compare lap times/i)).toBeInTheDocument());
        // Deselecting the only selected driver clears the fetch cache entirely, so
        // re-selecting fetches again rather than silently showing stale data.
        fireEvent.click(checkbox);
        await waitFor(() => expect(screen.queryByText(/select drivers above to compare lap times/i)).not.toBeInTheDocument());
        expect(api.getSessionLapData).toHaveBeenCalledTimes(2);
    });

    it("clears the lap data error path by removing a failed driver from the fetch cache so it can be retried", async () => {
        vi.mocked(api.getSessionLapData).mockRejectedValueOnce(new Error("boom"));

        await selectSession();
        fireEvent.click(screen.getByRole("checkbox", { name: /Lando Norris/ }));

        await waitFor(() => expect(api.getSessionLapData).toHaveBeenCalledTimes(1));
        // Still shows the "no data" placeholder rather than crashing.
        await waitFor(() =>
            expect(screen.getByText(/no lap data available for selected drivers/i)).toBeInTheDocument()
        );
    });

    it("cancelling the roster confirmation dialog does not start a stream", async () => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue({
            season_year: 2026,
            drivers: [{ team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false }],
        });

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /start live stream/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

        await waitFor(() => expect(screen.queryByText("Confirm Lineup Before Going Live")).not.toBeInTheDocument());
        expect(api.startLiveStream).not.toHaveBeenCalled();
    });

    it("closing the F1TV token dialog without validating leaves the live stream unstarted", async () => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue({
            season_year: 2026,
            drivers: [{ team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false }],
        });
        vi.mocked(api.getF1TvTokenStatus).mockResolvedValue({ valid: false, reason: "Token has expired" });

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /start live stream/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText("Update F1TV Token")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

        await waitFor(() => expect(screen.queryByText("Update F1TV Token")).not.toBeInTheDocument());
        expect(api.startLiveStream).not.toHaveBeenCalled();
    });

    it("shows the backend-provided detail message on a non-404 attach error response", async () => {
        vi.mocked(api.getTeamDriverPool).mockResolvedValue({
            season_year: 2026,
            drivers: [{ team_name: "McLaren", driver_number: 4, tla: "NOR", full_name: "Lando Norris", is_reserve: false }],
        });
        const axiosError = Object.assign(new Error("Server Error"), {
            isAxiosError: true,
            response: { status: 500, data: { detail: "Capture process crashed" } },
        });
        vi.mocked(api.attachLiveStream).mockRejectedValue(axiosError);

        render(
            <MemoryRouter>
                <Dashboard />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole("button", { name: /attach to live capture/i }));
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        await waitFor(() => expect(screen.getByText("Capture process crashed")).toBeInTheDocument());
    });
});
