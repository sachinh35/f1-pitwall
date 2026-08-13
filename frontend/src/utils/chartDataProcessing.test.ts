import { describe, expect, it } from "vitest";
import { mergeLapData, processLapDataForChart } from "./chartDataProcessing";
import { LapData, Stint } from "../services/api";
import { EnrichedF1SessionResult } from "../types";

const lap = (overrides: Partial<LapData>): LapData => ({
  meeting_key: 1,
  session_key: 100,
  driver_number: 1,
  lap_number: 1,
  date_start: null,
  duration_sector_1: null,
  duration_sector_2: null,
  duration_sector_3: null,
  lap_duration: 90,
  i1_speed: null,
  i2_speed: null,
  st_speed: null,
  is_pit_out_lap: false,
  segments_sector_1: null,
  segments_sector_2: null,
  ...overrides,
});

const result = (overrides: Partial<EnrichedF1SessionResult>): EnrichedF1SessionResult => ({
  dnf: false,
  dns: false,
  dsq: false,
  driver_number: 1,
  number_of_laps: 50,
  meeting_key: 1,
  session_key: 100,
  duration: 5000,
  gap_to_leader: null,
  position: 1,
  full_name: "Driver One",
  name_acronym: "DR1",
  first_name: "Driver",
  last_name: "One",
  country_code: "GBR",
  ...overrides,
});

describe("processLapDataForChart", () => {
  it("builds one data point per lap up to the max lap number across selected drivers", () => {
    const laps = [lap({ driver_number: 1, lap_number: 1 }), lap({ driver_number: 1, lap_number: 3 })];
    const { data, maxLapNumber } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })]);

    expect(maxLapNumber).toBe(3);
    expect(data).toHaveLength(3);
    expect(data[0].lap).toBe("Lap 1");
    expect(data[0].driver_1).toBe(90);
    expect(data[1].driver_1).toBeNull(); // lap 2 has no data for this driver
  });

  it("uses the session result's full_name, falling back to a generic label if missing", () => {
    const laps = [lap({ driver_number: 1 }), lap({ driver_number: 2 })];
    const { data } = processLapDataForChart(laps, [1, 2], [result({ driver_number: 1, full_name: "Lando Norris" })]);

    expect(data[0].driver_1_name).toBe("Lando Norris");
    expect(data[0].driver_2_name).toBe("Driver 2");
  });

  it("flags pit-out laps per driver per lap", () => {
    const laps = [lap({ driver_number: 1, lap_number: 1, is_pit_out_lap: true })];
    const { data } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })]);

    expect(data[0].driver_1_pit_out).toBe(true);
  });

  it("returns an empty data array (maxLapNumber 0) when there is no lap data at all", () => {
    const { data, maxLapNumber } = processLapDataForChart([], [1], [result({ driver_number: 1 })]);
    expect(maxLapNumber).toBe(0);
    expect(data).toEqual([]);
  });

  it("ignores lap data for drivers not in selectedDrivers", () => {
    const laps = [lap({ driver_number: 1, lap_number: 1 }), lap({ driver_number: 99, lap_number: 5 })];
    const { maxLapNumber } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })]);
    expect(maxLapNumber).toBe(1);
  });

  describe("with stints", () => {
    const stint = (overrides: Partial<Stint>): Stint => ({
      meeting_key: 1,
      session_key: 100,
      driver_number: 1,
      stint_number: 1,
      lap_start: 1,
      lap_end: 3,
      compound: "SOFT",
      tyre_age_at_start: 0,
      ...overrides,
    });

    it("tags each lap in the stint's range with compound and incrementing tyre age", () => {
      const laps = [lap({ driver_number: 1, lap_number: 1 }), lap({ driver_number: 1, lap_number: 2 })];
      const { data } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })], [stint({})]);

      expect(data[0].driver_1_compound).toBe("SOFT");
      expect(data[0].driver_1_tyre_age).toBe(1);
      expect(data[1].driver_1_tyre_age).toBe(2);
      expect(data[0].driver_1_is_scrub_set).toBe(false);
    });

    it("marks a stint with a non-zero starting tyre age as a scrub set", () => {
      const laps = [lap({ driver_number: 1, lap_number: 1 })];
      const { data } = processLapDataForChart(
        laps,
        [1],
        [result({ driver_number: 1 })],
        [stint({ tyre_age_at_start: 8 })]
      );

      expect(data[0].driver_1_is_scrub_set).toBe(true);
      expect(data[0].driver_1_tyre_age).toBe(9);
    });

    it("leaves compound/tyre-age null for laps not covered by any stint", () => {
      const laps = [lap({ driver_number: 1, lap_number: 10 })];
      const { data } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })], [stint({})]);

      const lap10 = data.find((d) => d.lapNumber === 10)!;
      expect(lap10.driver_1_compound).toBeNull();
      expect(lap10.driver_1_tyre_age).toBeNull();
    });

    it("falls back to null compound when a stint carries no compound value", () => {
      const laps = [lap({ driver_number: 1, lap_number: 1 })];
      const { data } = processLapDataForChart(laps, [1], [result({ driver_number: 1 })], [stint({ compound: null })]);
      expect(data[0].driver_1_compound).toBeNull();
    });

    it("defaults a stint's starting tyre age to 0 when not provided", () => {
      const laps = [lap({ driver_number: 1, lap_number: 1 })];
      const { data } = processLapDataForChart(
        laps,
        [1],
        [result({ driver_number: 1 })],
        [stint({ tyre_age_at_start: null })]
      );
      expect(data[0].driver_1_tyre_age).toBe(1);
      expect(data[0].driver_1_is_scrub_set).toBe(false);
    });

    it("ignores stints for drivers not in selectedDrivers", () => {
      const laps = [lap({ driver_number: 1, lap_number: 1 })];
      const { data } = processLapDataForChart(
        laps,
        [1],
        [result({ driver_number: 1 })],
        [stint({ driver_number: 99 })]
      );
      expect(data[0].driver_1_compound).toBeNull();
    });
  });
});

describe("mergeLapData", () => {
  it("combines existing and new lap data with no overlap", () => {
    const existing = [lap({ session_key: 1, driver_number: 1, lap_number: 1 })];
    const incoming = [lap({ session_key: 1, driver_number: 2, lap_number: 1 })];
    const merged = mergeLapData(existing, incoming);
    expect(merged).toHaveLength(2);
  });

  it("lets new data overwrite existing data for the same session/driver/lap key", () => {
    const existing = [lap({ session_key: 1, driver_number: 1, lap_number: 1, lap_duration: 90 })];
    const incoming = [lap({ session_key: 1, driver_number: 1, lap_number: 1, lap_duration: 88 })];
    const merged = mergeLapData(existing, incoming);
    expect(merged).toHaveLength(1);
    expect(merged[0].lap_duration).toBe(88);
  });

  it("returns an empty array when both inputs are empty", () => {
    expect(mergeLapData([], [])).toEqual([]);
  });
});
