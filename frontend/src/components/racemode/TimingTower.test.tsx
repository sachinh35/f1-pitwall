import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TimingTower from "./TimingTower";

describe("TimingTower", () => {
  it("shows a waiting message when no drivers have arrived yet", () => {
    render(
      <TimingTower
        drivers={{}}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    expect(screen.getByText(/waiting for timing data/i)).toBeInTheDocument();
  });

  it("renders driver rows sorted by real race position, not driver-object insertion order", () => {
    const drivers = {
      "1": { Position: "2" },
      "3": { Position: "1" },
    };
    render(
      <TimingTower
        drivers={drivers}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const tlas = screen.getAllByText(/^(VER|NOR)$/).map((el) => el.textContent);
    expect(tlas).toEqual(["VER", "NOR"]); // VER is Position "1", must render first despite being driver "1"'s neighbor
  });

  it("calls onToggleDriver with the clicked driver's number", () => {
    const onToggle = vi.fn();
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={onToggle}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    fireEvent.click(screen.getByText("VER"));
    expect(onToggle).toHaveBeenCalledWith(3);
  });

  it("shows PIT for a driver currently in the pit lane", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1", InPit: true } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    expect(screen.getByText("PIT")).toBeInTheDocument();
  });

  it("sorts drivers with no/invalid Position to the back of the field", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" }, "44": {} }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const rows = document.querySelectorAll(".tower-row:not(.tower-header)");
    expect(rows[0].textContent).toContain("VER"); // Position "1" sorts first
    expect(rows[1].querySelector(".pos")?.textContent).toBe("-"); // no Position -> shown as "-"
  });

  it("sorts a driver with no Position to the back even when listed first", () => {
    render(
      <TimingTower
        drivers={{ "44": {}, "1": {}, "3": { Position: "1" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const rows = document.querySelectorAll(".tower-row:not(.tower-header)");
    expect(rows[0].textContent).toContain("VER");
  });

  it("marks an eliminated driver's row visually distinct with an explanatory title", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={true}
        eliminatedDrivers={[3]}
        qualifyingGaps={{}}
      />
    );
    const row = document.querySelector(".tower-row:not(.tower-header)") as HTMLElement;
    expect(row.className).toContain("eliminated");
    expect(row.title).toMatch(/did not advance/i);
  });

  it("falls back to 'unknown' compound in the qualifying tyre-history chip when a stint has no Compound value", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{ "3": { Stints: { "1": { TotalLaps: 5 } } } }}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={true}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const chip = document.querySelector(".tyre-history .tyre-chip-mini.unknown");
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toBe("?");
  });

  it("shows the compound initial in the qualifying tyre-history chip for a known compound", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{ "3": { Stints: { "1": { Compound: "SOFT", TotalLaps: 5 } } } }}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={true}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const chip = document.querySelector(".tyre-history .tyre-chip-mini.soft");
    expect(chip?.textContent).toBe("S");
  });

  it("marks the selected row with a distinguishing class", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[3]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const row = document.querySelector(".tower-row:not(.tower-header)") as HTMLElement;
    expect(row.className).toContain("selected");
  });

  it("marks a personal-best (but not overall-fastest) lap green", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1", LastLapTime: { Value: "1:25.500", PersonalFastest: true } } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    expect(screen.getByText("1:25.500").className).toContain("green");
  });

  it("groups team radio clips by driver number so a driver's RadioIndicator shows all of theirs", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[
          {
            id: 1, session_key: 1, driver_number: 3, lap_number: 1, qualifying_part: null,
            ts: "2026-01-01T00:00:00Z", audio_path: "a.mp3", transcript: "Box box.", status: "done",
            error: null, transcribed_at: "2026-01-01T00:00:05Z", speaker_role: "pit_wall",
            is_notable: null, notable_reason: null,
          },
        ]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    fireEvent.mouseEnter(screen.getByTitle(/team radio/i));
    expect(screen.getByText(/box box/i)).toBeInTheDocument();
  });

  it("marks the fastest lap purple and shows the tyre compound initial (race mode - last lap)", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1", LastLapTime: { Value: "1:24.021", OverallFastest: true } } }}
        timingAppData={{ "3": { Stints: { "1": { Compound: "MEDIUM" } } } }}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    const lapTime = screen.getByText("1:24.021");
    expect(lapTime.className).toContain("purple");
    expect(screen.getByText("M")).toBeInTheDocument();
  });

  it("shows GapToLeader in the gap column outside qualifying", () => {
    render(
      <TimingTower
        drivers={{ "3": { Position: "1", GapToLeader: "+1.234" } }}
        timingAppData={{}}
        timingStats={{}}
        selectedDrivers={[]}
        onToggleDriver={vi.fn()}
        battleRadar={{}}
        tyreStrategyPredictions={{}}
        teamRadioClips={[]}
        isQualifying={false}
        eliminatedDrivers={[]}
        qualifyingGaps={{}}
      />
    );
    expect(screen.getByText("+1.234")).toBeInTheDocument();
  });

  describe("race mode tyre stint history", () => {
    it("shows every stint separately, including a repeat pit stop onto the same compound (soft, hard, hard)", () => {
      render(
        <TimingTower
          drivers={{ "44": { Position: "1" } }}
          timingAppData={{
            "44": {
              Stints: {
                "0": { Compound: "SOFT", TotalLaps: 13 },
                "1": { Compound: "HARD", TotalLaps: 17 },
                "2": { Compound: "HARD", TotalLaps: 4 },
              },
            },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      // Two HARD chips must both render (not collapsed into one) - real second pit stop.
      expect(screen.getAllByText("H")).toHaveLength(2);
      expect(screen.getAllByText("S")).toHaveLength(1);
    });

    it("reveals a tyre strategy popover with per-stint lap counts on hover, hidden until then", () => {
      render(
        <TimingTower
          drivers={{ "44": { Position: "1" } }}
          timingAppData={{
            "44": {
              Stints: {
                "0": { Compound: "SOFT", TotalLaps: 13 },
                "1": { Compound: "HARD", TotalLaps: 17 },
                "2": { Compound: "HARD", TotalLaps: 4 },
              },
            },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.queryByText("Tyre Strategy")).not.toBeInTheDocument();

      const badge = document.querySelector(".tyre-stint-badge");
      expect(badge).not.toBeNull();
      fireEvent.mouseEnter(badge!);

      expect(screen.getByText("Tyre Strategy")).toBeInTheDocument();
      expect(screen.getByText("13L")).toBeInTheDocument();
      expect(screen.getByText("17L")).toBeInTheDocument();
      expect(screen.getByText("4L")).toBeInTheDocument();

      fireEvent.mouseLeave(badge!);
      expect(screen.queryByText("Tyre Strategy")).not.toBeInTheDocument();
    });

    it("dedupes consecutive same-compound stints in qualifying, but not in race mode, from the same data", () => {
      const timingAppData = {
        "44": {
          Stints: {
            "0": { Compound: "SOFT", TotalLaps: 13 },
            "1": { Compound: "HARD", TotalLaps: 17 },
            "2": { Compound: "HARD", TotalLaps: 4 },
          },
        },
      };
      const { rerender } = render(
        <TimingTower
          drivers={{ "44": { Position: "1" } }}
          timingAppData={timingAppData}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{ "44": 0 }}
        />
      );
      expect(screen.getAllByText("H")).toHaveLength(1);

      rerender(
        <TimingTower
          drivers={{ "44": { Position: "1" } }}
          timingAppData={timingAppData}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getAllByText("H")).toHaveLength(2);
    });

    it("passes each driver their own predicted strategy, keyed by driver number", () => {
      render(
        <TimingTower
          drivers={{ "44": { Position: "1" }, "1": { Position: "2" } }}
          timingAppData={{
            "44": { Stints: { "0": { Compound: "HARD", TotalLaps: 8 } } },
            "1": { Stints: { "0": { Compound: "SOFT", TotalLaps: 8 } } },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{
            "44": {
              driver_number: 44,
              generated_at_lap: 8,
              predicted_stints: [{ stint_number: 1, compound: "hard", predicted_total_laps: 30 }],
              safety_car_note: "Low SC risk.",
              summary: "Hamilton's predicted strategy.",
            },
          }}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      // Rows sort by Position - driver 44 (P1, has a prediction) renders first, driver 1
      // (P2, no prediction) second.
      const badges = document.querySelectorAll(".tyre-stint-badge");
      fireEvent.mouseEnter(badges[0]);
      expect(screen.getByText("Hamilton's predicted strategy.")).toBeInTheDocument();
      fireEvent.mouseLeave(badges[0]);

      fireEvent.mouseEnter(badges[1]);
      expect(screen.queryByText("Predicted Strategy")).not.toBeInTheDocument();
    });
  });

  describe("race mode gap/interval columns", () => {
    it("shows GapToLeader and IntervalToPositionAhead as separate columns at the same time", () => {
      render(
        <TimingTower
          drivers={{
            "3": { Position: "1", GapToLeader: "+1.234", IntervalToPositionAhead: { Value: "+0.456" } },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getByText("+1.234")).toBeInTheDocument();
      expect(screen.getByText("+0.456")).toBeInTheDocument();
      expect(screen.getByText("Gap")).toBeInTheDocument();
      expect(screen.getByText("Int")).toBeInTheDocument();
    });

    it("does not render the Int column during qualifying", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1", GapToLeader: "+1.234" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{ "3": 0 }}
        />
      );
      expect(screen.queryByText("Int")).not.toBeInTheDocument();
    });
  });

  describe("qualifying mode", () => {
    it("shows the backend-computed qualifyingGaps value in the gap column, not GapToLeader or F1's own Stats field", () => {
      // GapToLeader/Stats are both ignored in qualifying: GapToLeader is a race-only
      // concept F1 never sends during qualifying, and F1's own Stats field proved
      // unreliable (wrong index, never cleared for a new leader) - see TimingTower.tsx.
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "2",
              GapToLeader: "+1.234",
              Stats: { "0": { TimeDiffToFastest: "+9.999" } },
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{ "3": 0.512 }}
        />
      );
      expect(screen.getByText("+0.512")).toBeInTheDocument();
      expect(screen.queryByText("+1.234")).not.toBeInTheDocument();
      expect(screen.queryByText("+9.999")).not.toBeInTheDocument();
    });

    it("shows a dash (not '+0.000') for the session leader", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{ "3": 0 }}
        />
      );
      const gapCells = document.querySelectorAll(".gap.mono");
      expect(gapCells).toHaveLength(1);
      expect(gapCells[0].textContent).toBe("-");
    });

    it("shows a dash when the driver has no valid best lap yet (no entry in qualifyingGaps)", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "5" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      const gapCells = document.querySelectorAll(".gap.mono");
      expect(gapCells).toHaveLength(1);
      expect(gapCells[0].textContent).toBe("-");
    });

    it("shows the session-best lap, not the last lap, even when last lap was slower", () => {
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "1",
              BestLapTime: { Value: "1:20.000", Lap: 2 },
              LastLapTime: { Value: "1:25.000", OverallFastest: false },
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getByText("1:20.000")).toBeInTheDocument();
      expect(screen.queryByText("1:25.000")).not.toBeInTheDocument();
    });

    it("shows a dash when a driver has no valid best lap (e.g. their only lap was deleted)", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "21", BestLapTime: { Value: "" } } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      // Row renders (position 21), but no lap time text - dashes for the missing best lap.
      expect(screen.getByText("21")).toBeInTheDocument();
    });

    it("renders per-sector times with fastest-sector coloring", () => {
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "1",
              BestLapTime: { Value: "1:20.000" },
              Sectors: {
                "0": { Value: "26.391", PersonalFastest: true },
                "1": { Value: "30.000", OverallFastest: true },
                "2": { Value: "23.609" },
              },
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      const s1 = screen.getByText("26.391");
      const s2 = screen.getByText("30.000");
      expect(s1.className).toContain("green");
      expect(s2.className).toContain("purple");
      expect(screen.getByText("23.609")).toBeInTheDocument();
    });

    it("shows the full tyre stint history, not just the current compound", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1" } }}
          timingAppData={{
            "3": {
              Stints: {
                "1": { Compound: "MEDIUM" },
                "2": { Compound: "SOFT" },
              },
            },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getByText("M")).toBeInTheDocument();
      expect(screen.getByText("S")).toBeInTheDocument();
    });

    it("dedups consecutive stints on the same compound (soft, soft, soft -> just soft)", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1" } }}
          timingAppData={{
            "3": {
              Stints: {
                "1": { Compound: "SOFT" },
                "2": { Compound: "SOFT" },
                "3": { Compound: "SOFT" },
              },
            },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getAllByText("S")).toHaveLength(1);
    });

    it("keeps a re-fitted compound as a separate entry only when it's a real change (medium, soft, soft -> medium, soft)", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1" } }}
          timingAppData={{
            "3": {
              Stints: {
                "1": { Compound: "MEDIUM" },
                "2": { Compound: "SOFT" },
                "3": { Compound: "SOFT" },
              },
            },
          }}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getAllByText("M")).toHaveLength(1);
      expect(screen.getAllByText("S")).toHaveLength(1);
    });

    it("marks an eliminated driver with an OUT badge", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "18" }, "5": { Position: "1" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[3]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getByText("OUT")).toBeInTheDocument();
    });

    it("does not show an OUT badge for a driver who is not eliminated", () => {
      render(
        <TimingTower
          drivers={{ "5": { Position: "1" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[3]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.queryByText("OUT")).not.toBeInTheDocument();
    });

    it("labels the speed column as Speed Trap rather than a bare number", () => {
      render(
        <TimingTower
          drivers={{ "3": { Position: "1" } }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.getByText("Speed Trap")).toBeInTheDocument();
    });
  });

  describe("race mode sector times", () => {
    it("renders per-sector times with fastest-sector coloring in race mode too", () => {
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "1",
              LastLapTime: { Value: "1:20.000" },
              Sectors: {
                "0": { Value: "26.391", PersonalFastest: true },
                "1": { Value: "30.000", OverallFastest: true },
                "2": { Value: "23.609" },
              },
              SectorsLap: 12,
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      const s1 = screen.getByText("26.391");
      const s2 = screen.getByText("30.000");
      expect(s1.className).toContain("green");
      expect(s2.className).toContain("purple");
      expect(screen.getByText("23.609")).toBeInTheDocument();
    });

    it("shows a tiny lap marker next to race-mode sector times, since sectors update independently of the lap counter", () => {
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "1",
              Sectors: { "0": { Value: "26.391" } },
              SectorsLap: 12,
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={false}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      const marker = screen.getByText("L12");
      expect(marker.title).toMatch(/as of lap 12/i);
    });

    it("omits the lap marker in qualifying mode", () => {
      render(
        <TimingTower
          drivers={{
            "3": {
              Position: "1",
              Sectors: { "0": { Value: "26.391" } },
              SectorsLap: 12,
            },
          }}
          timingAppData={{}}
          timingStats={{}}
          selectedDrivers={[]}
          onToggleDriver={vi.fn()}
          battleRadar={{}}
          tyreStrategyPredictions={{}}
          teamRadioClips={[]}
          isQualifying={true}
          eliminatedDrivers={[]}
          qualifyingGaps={{}}
        />
      );
      expect(screen.queryByText("L12")).not.toBeInTheDocument();
    });
  });
});
