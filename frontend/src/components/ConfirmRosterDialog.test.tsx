import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ConfirmRosterDialog from "./ConfirmRosterDialog";
import { ConfirmedRosterEntry, getTeamDriverPool, GetTeamDriverPoolResponse } from "../services/api";

vi.mock("../services/api", () => ({
    getTeamDriverPool: vi.fn(),
}));

const mockedGetTeamDriverPool = vi.mocked(getTeamDriverPool);

const buildPool = (): GetTeamDriverPoolResponse => ({
    season_year: 2026,
    drivers: [
        { team_name: "McLaren", driver_number: 1, tla: "NOR", full_name: "Lando Norris", is_reserve: false },
        { team_name: "McLaren", driver_number: 81, tla: "PIA", full_name: "Oscar Piastri", is_reserve: false },
        { team_name: "McLaren", driver_number: null, tla: null, full_name: "Leonardo Fornaroli", is_reserve: true },
        { team_name: "McLaren", driver_number: null, tla: null, full_name: "Pato O'Ward", is_reserve: true },
        { team_name: "Red Bull Racing", driver_number: 3, tla: "VER", full_name: "Max Verstappen", is_reserve: false },
        { team_name: "Red Bull Racing", driver_number: 30, tla: "LAW", full_name: "Liam Lawson", is_reserve: false },
        { team_name: "Red Bull Racing", driver_number: 22, tla: "TSU", full_name: "Yuki Tsunoda", is_reserve: true },
        { team_name: "Audi", driver_number: 5, tla: "BOR", full_name: "Gabriel Bortoleto", is_reserve: false },
        { team_name: "Audi", driver_number: 27, tla: "HUL", full_name: "Nico Hulkenberg", is_reserve: false },
        { team_name: "Racing Bulls", driver_number: 6, tla: "HAD", full_name: "Isack Hadjar", is_reserve: false },
        { team_name: "Racing Bulls", driver_number: 41, tla: "LIN", full_name: "Arvid Lindblad", is_reserve: false },
        { team_name: "Alpine", driver_number: 10, tla: "GAS", full_name: "Pierre Gasly", is_reserve: false },
        { team_name: "Alpine", driver_number: 43, tla: "COL", full_name: "Franco Colapinto", is_reserve: false },
        { team_name: "Cadillac", driver_number: 11, tla: "PER", full_name: "Sergio Perez", is_reserve: false },
        { team_name: "Cadillac", driver_number: 77, tla: "BOT", full_name: "Valtteri Bottas", is_reserve: false },
        { team_name: "Mercedes", driver_number: 12, tla: "ANT", full_name: "Kimi Antonelli", is_reserve: false },
        { team_name: "Mercedes", driver_number: 63, tla: "RUS", full_name: "George Russell", is_reserve: false },
        { team_name: "Aston Martin", driver_number: 14, tla: "ALO", full_name: "Fernando Alonso", is_reserve: false },
        { team_name: "Aston Martin", driver_number: 18, tla: "STR", full_name: "Lance Stroll", is_reserve: false },
        { team_name: "Ferrari", driver_number: 16, tla: "LEC", full_name: "Charles Leclerc", is_reserve: false },
        { team_name: "Ferrari", driver_number: 44, tla: "HAM", full_name: "Lewis Hamilton", is_reserve: false },
        { team_name: "Williams", driver_number: 23, tla: "ALB", full_name: "Alexander Albon", is_reserve: false },
        { team_name: "Williams", driver_number: 55, tla: "SAI", full_name: "Carlos Sainz", is_reserve: false },
        { team_name: "Haas", driver_number: 31, tla: "OCO", full_name: "Esteban Ocon", is_reserve: false },
        { team_name: "Haas", driver_number: 87, tla: "BEA", full_name: "Oliver Bearman", is_reserve: false },
    ],
});

beforeEach(() => {
    mockedGetTeamDriverPool.mockReset();
});

describe("ConfirmRosterDialog", () => {
    it("renders all 22 default drivers grouped by team once loaded", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);

        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        // 22 race-seat drivers rendered
        expect(screen.getByText("Lando Norris")).toBeInTheDocument();
        expect(screen.getByText("Oscar Piastri")).toBeInTheDocument();
        expect(screen.getByText("Max Verstappen")).toBeInTheDocument();
        expect(screen.getByText("Oliver Bearman")).toBeInTheDocument();

        // Reserve drivers are not shown by default
        expect(screen.queryByText("Leonardo Fornaroli")).not.toBeInTheDocument();

        // Team name grouping present
        expect(screen.getByText("McLaren")).toBeInTheDocument();
        expect(screen.getAllByText("Change")).toHaveLength(22);
    });

    it("editing a row via the reserve dropdown updates its driver info", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-McLaren-1");
        fireEvent.click(within(row).getByText("Change"));

        const select = within(row).getByLabelText("McLaren substitute driver");
        fireEvent.mouseDown(select);
        const listbox = within(screen.getByRole("listbox"));
        fireEvent.click(listbox.getByText("Leonardo Fornaroli (no number on file)"));

        // driver number & tla fields should be blank/editable since reserve has none on file
        expect(within(row).getByLabelText("McLaren driver number")).toHaveValue(null);
        expect(within(row).getByLabelText("McLaren TLA")).toHaveValue("");
    });

    it("clicking Change for a team with no reserves on file jumps straight to a blank custom entry", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Isack Hadjar")).toBeInTheDocument());

        // Racing Bulls has no reserve entries in the pool fixture.
        const row = screen.getByTestId("roster-row-Racing Bulls-6");
        fireEvent.click(within(row).getByText("Change"));

        expect(within(row).getByPlaceholderText("Full name")).toHaveValue("");
        expect(within(row).getByLabelText("Racing Bulls driver number")).toHaveValue(null);
    });

    it("switching to Custom for a team that does have reserves clears the fields, and typing a name updates it", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-McLaren-1");
        fireEvent.click(within(row).getByText("Change"));
        const select = within(row).getByLabelText("McLaren substitute driver");
        fireEvent.mouseDown(select);
        fireEvent.click(within(screen.getByRole("listbox")).getByText("Custom..."));

        const nameField = within(row).getByPlaceholderText("Full name");
        expect(nameField).toHaveValue("");

        fireEvent.change(nameField, { target: { value: "Test Driver" } });
        expect(nameField).toHaveValue("Test Driver");
    });

    it("Reset to default restores a row's original driver info after editing", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-McLaren-1");
        fireEvent.click(within(row).getByText("Change"));
        expect(within(row).getByLabelText("McLaren substitute driver")).toBeInTheDocument();

        fireEvent.click(within(row).getByText("Reset to default"));

        expect(within(row).queryByLabelText("McLaren substitute driver")).not.toBeInTheDocument();
        expect(screen.getByText("Lando Norris")).toBeInTheDocument();
    });

    it("selecting a reserve that does have a driver number on file fills it in", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Max Verstappen")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-Red Bull Racing-3");
        fireEvent.click(within(row).getByText("Change"));
        const select = within(row).getByLabelText("Red Bull Racing substitute driver");
        fireEvent.mouseDown(select);
        fireEvent.click(within(screen.getByRole("listbox")).getByText("Yuki Tsunoda"));

        expect(within(row).getByLabelText("Red Bull Racing driver number")).toHaveValue(22);
    });

    it("renders a blank TLA/driver number when a seat's pool entry is itself missing them", async () => {
        mockedGetTeamDriverPool.mockResolvedValue({
            season_year: 2026,
            drivers: [
                { team_name: "TBD Team", driver_number: null, tla: null, full_name: "Driver TBD", is_reserve: false },
            ],
        });
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Driver TBD")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-TBD Team-null");
        expect(within(row).getByText("Change")).toBeInTheDocument();
    });

    it("Confirm & Start is disabled until every edited row is valid, then enables once filled in", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        const confirmButton = screen.getByRole("button", { name: "Confirm & Start" });
        expect(confirmButton).not.toBeDisabled();

        const row = screen.getByTestId("roster-row-McLaren-1");
        fireEvent.click(within(row).getByText("Change"));
        // Now in edit mode with no selection made yet -> invalid
        expect(confirmButton).toBeDisabled();

        const select = within(row).getByLabelText("McLaren substitute driver");
        fireEvent.mouseDown(select);
        fireEvent.click(within(screen.getByRole("listbox")).getByText("Leonardo Fornaroli (no number on file)"));

        // Still invalid: number/tla blank
        expect(confirmButton).toBeDisabled();

        fireEvent.change(within(row).getByLabelText("McLaren driver number"), { target: { value: "50" } });
        fireEvent.change(within(row).getByLabelText("McLaren TLA"), { target: { value: "FOR" } });

        expect(confirmButton).not.toBeDisabled();
    });

    it("confirming calls onConfirm with a correctly-shaped roster including resolved team colours", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        const onConfirm = vi.fn();
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={onConfirm} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        const row = screen.getByTestId("roster-row-McLaren-1");
        fireEvent.click(within(row).getByText("Change"));
        const select = within(row).getByLabelText("McLaren substitute driver");
        fireEvent.mouseDown(select);
        fireEvent.click(within(screen.getByRole("listbox")).getByText("Leonardo Fornaroli (no number on file)"));
        fireEvent.change(within(row).getByLabelText("McLaren driver number"), { target: { value: "50" } });
        fireEvent.change(within(row).getByLabelText("McLaren TLA"), { target: { value: "FOR" } });

        fireEvent.click(screen.getByRole("button", { name: "Confirm & Start" }));

        expect(onConfirm).toHaveBeenCalledTimes(1);
        const roster = onConfirm.mock.calls[0][0];
        expect(roster).toHaveLength(22);

        const edited = roster.find((entry: ConfirmedRosterEntry) => entry.full_name === "Leonardo Fornaroli");
        expect(edited).toEqual({
            driver_number: 50,
            tla: "FOR",
            full_name: "Leonardo Fornaroli",
            team_name: "McLaren",
            team_colour: "#F58020",
        });

        const untouched = roster.find((entry: ConfirmedRosterEntry) => entry.full_name === "Max Verstappen");
        expect(untouched).toEqual({
            driver_number: 3,
            tla: "VER",
            full_name: "Max Verstappen",
            team_name: "Red Bull Racing",
            team_colour: "#3671C6",
        });
    });

    it("cancel calls onClose without calling onConfirm", async () => {
        mockedGetTeamDriverPool.mockResolvedValue(buildPool());
        const onClose = vi.fn();
        const onConfirm = vi.fn();
        render(<ConfirmRosterDialog open onClose={onClose} onConfirm={onConfirm} />);
        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

        expect(onClose).toHaveBeenCalledTimes(1);
        expect(onConfirm).not.toHaveBeenCalled();
    });

    it("shows an error state with a retry button when the fetch fails, instead of crashing", async () => {
        mockedGetTeamDriverPool.mockRejectedValueOnce(new Error("network down"));
        render(<ConfirmRosterDialog open onClose={vi.fn()} onConfirm={vi.fn()} />);

        await waitFor(() => expect(screen.getByText(/failed to load/i)).toBeInTheDocument());
        const retryButton = screen.getByRole("button", { name: "Retry" });

        mockedGetTeamDriverPool.mockResolvedValueOnce(buildPool());
        fireEvent.click(retryButton);

        await waitFor(() => expect(screen.getByText("Lando Norris")).toBeInTheDocument());
        expect(screen.queryByText(/failed to load/i)).not.toBeInTheDocument();
    });
});
