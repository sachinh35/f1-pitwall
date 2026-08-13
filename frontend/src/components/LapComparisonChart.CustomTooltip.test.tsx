import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CustomTooltip, CustomTooltipProps } from "./LapComparisonChart";

const driverInfo = [{ driverNumber: 1, name: "Lando Norris", color: "#F58020" }];

function dataPoint(overrides: Record<string, unknown> = {}) {
    return {
        lap: "Lap 3",
        lapNumber: 3,
        driver_1: 88,
        driver_1_pit_out: false,
        driver_1_compound: null,
        driver_1_tyre_age: null,
        driver_1_is_scrub_set: false,
        ...overrides,
    };
}

function baseProps(overrides: Partial<CustomTooltipProps> = {}): CustomTooltipProps {
    return {
        active: true,
        label: "Lap 3",
        driverInfo,
        payload: [
            {
                dataKey: "driver_1",
                value: 88,
                color: "#F58020",
                payload: dataPoint(),
            },
        ],
        ...overrides,
    } as CustomTooltipProps;
}

describe("CustomTooltip", () => {
    it("renders nothing when not active", () => {
        const { container } = render(<CustomTooltip {...baseProps({ active: false })} />);
        expect(container).toBeEmptyDOMElement();
    });

    it("renders nothing when there is no payload", () => {
        const { container } = render(<CustomTooltip {...baseProps({ payload: undefined })} />);
        expect(container).toBeEmptyDOMElement();
    });

    it("renders nothing when the payload is empty", () => {
        const { container } = render(<CustomTooltip {...baseProps({ payload: [] })} />);
        expect(container).toBeEmptyDOMElement();
    });

    it("renders the lap label and formatted lap duration when active with data", () => {
        render(<CustomTooltip {...baseProps()} />);
        expect(screen.getByText("Lap 3")).toBeInTheDocument();
        expect(screen.getByText(/Lando Norris: 1:28\.000/)).toBeInTheDocument();
    });

    it("falls back to a generic 'Driver N' label when driverInfo has no match", () => {
        render(<CustomTooltip {...baseProps({ driverInfo: [] })} />);
        expect(screen.getByText(/Driver 1: 1:28\.000/)).toBeInTheDocument();
    });

    it("shows N/A for a driver with no value on this lap, without a driver name lookup failure", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [{ dataKey: "driver_1", value: null, color: "#F58020", payload: dataPoint({ driver_1: null }) }],
                })}
            />
        );
        expect(screen.getByText(/Lando Norris: N\/A/)).toBeInTheDocument();
    });

    it("shows a Pit Out chip only for a pit-out lap", () => {
        const { rerender } = render(<CustomTooltip {...baseProps()} />);
        expect(screen.queryByText("Pit Out")).not.toBeInTheDocument();

        rerender(
            <CustomTooltip
                {...baseProps({
                    payload: [{ dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_pit_out: true }) }],
                })}
            />
        );
        expect(screen.getByText("Pit Out")).toBeInTheDocument();
    });

    it("renders a compound icon for a recognized compound", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [{ dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_compound: "SOFT" }) }],
                })}
            />
        );
        expect(screen.getByAltText("SOFT tire")).toBeInTheDocument();
    });

    it("renders no compound icon for an unrecognized compound (no icon URL)", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [
                        { dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_compound: "UNKNOWN" }) },
                    ],
                })}
            />
        );
        expect(screen.queryByAltText(/tire/)).not.toBeInTheDocument();
    });

    it("renders no compound icon when compound is null", () => {
        render(<CustomTooltip {...baseProps()} />);
        expect(screen.queryByAltText(/tire/)).not.toBeInTheDocument();
    });

    it("shows singular tyre age phrasing for exactly 1 lap", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [{ dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_tyre_age: 1 }) }],
                })}
            />
        );
        expect(screen.getByText("(1 lap on tyre)")).toBeInTheDocument();
    });

    it("shows plural tyre age phrasing for more than 1 lap", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [{ dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_tyre_age: 5 }) }],
                })}
            />
        );
        expect(screen.getByText("(5 laps on tyre)")).toBeInTheDocument();
    });

    it("shows no tyre age text when tyre age is not a number", () => {
        render(<CustomTooltip {...baseProps()} />);
        expect(screen.queryByText(/on tyre/)).not.toBeInTheDocument();
    });

    it("shows a Scrub set chip only when the lap is on a scrub-set stint", () => {
        const { rerender } = render(<CustomTooltip {...baseProps()} />);
        expect(screen.queryByText("Scrub set")).not.toBeInTheDocument();

        rerender(
            <CustomTooltip
                {...baseProps({
                    payload: [
                        { dataKey: "driver_1", value: 88, color: "#F58020", payload: dataPoint({ driver_1_is_scrub_set: true }) },
                    ],
                })}
            />
        );
        expect(screen.getByText("Scrub set")).toBeInTheDocument();
    });

    it("strips a _pit_out dataKey suffix when resolving which driver a payload entry belongs to", () => {
        render(
            <CustomTooltip
                {...baseProps({
                    payload: [
                        { dataKey: "driver_1_pit_out", value: 88, color: "#F58020", payload: dataPoint() },
                    ],
                })}
            />
        );
        expect(screen.getByText(/Lando Norris: 1:28\.000/)).toBeInTheDocument();
    });
});
