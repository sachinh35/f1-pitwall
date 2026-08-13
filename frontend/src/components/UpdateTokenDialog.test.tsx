import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import UpdateTokenDialog from "./UpdateTokenDialog";
import { updateF1TvToken } from "../services/api";

vi.mock("../services/api", () => ({
    updateF1TvToken: vi.fn(),
}));

const mockedUpdateF1TvToken = vi.mocked(updateF1TvToken);

beforeEach(() => {
    mockedUpdateF1TvToken.mockReset();
});

describe("UpdateTokenDialog", () => {
    it("renders with the submit button disabled until a token is pasted", () => {
        render(<UpdateTokenDialog open onClose={vi.fn()} onValidated={vi.fn()} reason="Your F1TV token is missing or expired." />);

        expect(screen.getByText("Your F1TV token is missing or expired.", { exact: false })).toBeInTheDocument();
        const submitButton = screen.getByRole("button", { name: "I've updated the token" });
        expect(submitButton).toBeDisabled();

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "raw.jwt.token" } });
        expect(submitButton).not.toBeDisabled();
    });

    it("pasting a valid token and submitting calls onValidated", async () => {
        mockedUpdateF1TvToken.mockResolvedValue({ valid: true });
        const onValidated = vi.fn();
        render(<UpdateTokenDialog open onClose={vi.fn()} onValidated={onValidated} reason={null} />);

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "  raw.jwt.token  " } });
        fireEvent.click(screen.getByRole("button", { name: "I've updated the token" }));

        await waitFor(() => expect(onValidated).toHaveBeenCalledTimes(1));
        expect(mockedUpdateF1TvToken).toHaveBeenCalledWith("raw.jwt.token");
    });

    it("submitting an invalid token shows the error and keeps the dialog open, without calling onValidated", async () => {
        mockedUpdateF1TvToken.mockResolvedValue({ valid: false, reason: "Token has expired" });
        const onValidated = vi.fn();
        render(<UpdateTokenDialog open onClose={vi.fn()} onValidated={onValidated} reason={null} />);

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "expired.jwt.token" } });
        fireEvent.click(screen.getByRole("button", { name: "I've updated the token" }));

        await waitFor(() => expect(screen.getByText("Token has expired")).toBeInTheDocument());
        expect(onValidated).not.toHaveBeenCalled();
        // Dialog stays open with the paste box still available for another attempt
        expect(screen.getByLabelText("F1TV JWT token")).toBeInTheDocument();
    });

    it("falls back to a generic invalid-token message when the server gives no reason", async () => {
        mockedUpdateF1TvToken.mockResolvedValue({ valid: false });
        render(<UpdateTokenDialog open onClose={vi.fn()} onValidated={vi.fn()} reason={null} />);

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "bad.jwt.token" } });
        fireEvent.click(screen.getByRole("button", { name: "I've updated the token" }));

        await waitFor(() => expect(screen.getByText("Token is not valid.")).toBeInTheDocument());
    });

    it("a thrown/network error shows a generic error and keeps the dialog open", async () => {
        mockedUpdateF1TvToken.mockRejectedValue(new Error("network down"));
        const onValidated = vi.fn();
        render(<UpdateTokenDialog open onClose={vi.fn()} onValidated={onValidated} reason={null} />);

        fireEvent.change(screen.getByLabelText("F1TV JWT token"), { target: { value: "raw.jwt.token" } });
        fireEvent.click(screen.getByRole("button", { name: "I've updated the token" }));

        await waitFor(() => expect(screen.getByText(/failed to validate the token/i)).toBeInTheDocument());
        expect(onValidated).not.toHaveBeenCalled();
    });

    it("resets its state whenever open flips true", () => {
        const { rerender } = render(
            <UpdateTokenDialog open={false} onClose={vi.fn()} onValidated={vi.fn()} reason={null} />
        );
        rerender(<UpdateTokenDialog open onClose={vi.fn()} onValidated={vi.fn()} reason={null} />);

        expect(screen.getByLabelText("F1TV JWT token")).toHaveValue("");
    });

    it("cancel calls onClose", () => {
        const onClose = vi.fn();
        render(<UpdateTokenDialog open onClose={onClose} onValidated={vi.fn()} reason={null} />);

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});
