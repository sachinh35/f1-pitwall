/**
 * Utility functions for processing chart data
 */
import { LapData, Stint } from '../services/api';
import { EnrichedF1SessionResult } from '../types';

export interface DriverLapInfo {
    lap_duration: number | null;
    is_pit_out_lap: boolean;
}

export interface ProcessedChartData {
    data: { [key: string]: number | null | string | boolean }[];
    maxLapNumber: number;
}

/**
 * Process lap data for chart rendering
 */
export const processLapDataForChart = (
    lapData: LapData[],
    selectedDrivers: number[],
    sessionResults: EnrichedF1SessionResult[],
    stints?: Stint[]
): ProcessedChartData => {
    // Group lap data by driver (including pit out lap info)
    const driverLaps: { 
        [driverNumber: number]: { 
            [lapNumber: number]: DriverLapInfo
        } 
    } = {};
    
    selectedDrivers.forEach(driverNum => {
        driverLaps[driverNum] = {};
    });

    lapData.forEach(lap => {
        if (selectedDrivers.includes(lap.driver_number)) {
            driverLaps[lap.driver_number][lap.lap_number] = {
                lap_duration: lap.lap_duration,
                is_pit_out_lap: lap.is_pit_out_lap,
            };
        }
    });

    // Find max lap number across all selected drivers
    const maxLapNumber = Math.max(
        ...selectedDrivers.map(driverNum => {
            const laps = driverLaps[driverNum];
            return laps ? Math.max(...Object.keys(laps).map(Number), 0) : 0;
        }),
        0
    );

    // Build compound, tyre age, and scrub flags per driver per lap from stints (if provided)
    const compoundByDriverLap: { [driverNumber: number]: { [lap: number]: string | null } } = {};
    const tyreAgeByDriverLap: { [driverNumber: number]: { [lap: number]: number | null } } = {};
    const scrubByDriverLap: { [driverNumber: number]: { [lap: number]: boolean } } = {};
    if (stints && stints.length > 0) {
        selectedDrivers.forEach(d => {
            compoundByDriverLap[d] = {};
            tyreAgeByDriverLap[d] = {};
            scrubByDriverLap[d] = {};
        });
        stints.forEach(s => {
            if (selectedDrivers.includes(s.driver_number)) {
                const baseAge = s.tyre_age_at_start ?? 0;
                const isScrubSet = baseAge !== 0;
                for (let lapNum = s.lap_start; lapNum <= s.lap_end; lapNum++) {
                    compoundByDriverLap[s.driver_number][lapNum] = s.compound || null;
                    // Tyre age is base age plus number of completed laps on this stint (starting at 1)
                    // e.g. new tyres (baseAge=0): lap_start -> 1, next lap -> 2, etc.
                    tyreAgeByDriverLap[s.driver_number][lapNum] = baseAge + (lapNum - s.lap_start) + 1;
                    scrubByDriverLap[s.driver_number][lapNum] = isScrubSet;
                }
            }
        });
    }

    // Build chart data structure
    const data: { [key: string]: number | null | string | boolean }[] = [];
    
    for (let lapNum = 1; lapNum <= maxLapNumber; lapNum++) {
        const dataPoint: { [key: string]: number | null | string | boolean } = {
            lap: `Lap ${lapNum}`,
            lapNumber: lapNum,
        };

        selectedDrivers.forEach((driverNum) => {
            const driverName = sessionResults.find(r => r.driver_number === driverNum)?.full_name || `Driver ${driverNum}`;
            const lapInfo = driverLaps[driverNum]?.[lapNum];
            const lapDuration = lapInfo?.lap_duration ?? null;
            const isPitOutLap = lapInfo?.is_pit_out_lap ?? false;
            const compound = compoundByDriverLap[driverNum]?.[lapNum] ?? null;
            const tyreAge = tyreAgeByDriverLap[driverNum]?.[lapNum] ?? null;
            const isScrubSet = scrubByDriverLap[driverNum]?.[lapNum] ?? false;
            
            dataPoint[`driver_${driverNum}`] = lapDuration;
            dataPoint[`driver_${driverNum}_name`] = driverName;
            dataPoint[`driver_${driverNum}_pit_out`] = isPitOutLap;
            dataPoint[`driver_${driverNum}_compound`] = compound;
            dataPoint[`driver_${driverNum}_tyre_age`] = tyreAge;
            dataPoint[`driver_${driverNum}_is_scrub_set`] = isScrubSet;
        });

        data.push(dataPoint);
    }

    return { data, maxLapNumber };
};

/**
 * Merge new lap data with existing lap data
 */
export const mergeLapData = (existingData: LapData[], newData: LapData[]): LapData[] => {
    const dataMap = new Map<string, LapData>();
    
    // Add existing data to map
    existingData.forEach(lap => {
        const key = `${lap.session_key}_${lap.driver_number}_${lap.lap_number}`;
        dataMap.set(key, lap);
    });
    
    // Add/update with new data
    newData.forEach(lap => {
        const key = `${lap.session_key}_${lap.driver_number}_${lap.lap_number}`;
        dataMap.set(key, lap);
    });
    
    return Array.from(dataMap.values());
};

