import { useState } from "react";

/** Compare Widget/Track Map/Lap Delta Chart all highlight the same "currently selected"
 * drivers - capped at 4 so overlaid comparison charts stay readable. */
export const MAX_SELECTED_DRIVERS = 4;

export interface DriverSelection {
  selectedDrivers: number[];
  /** Adds the driver if not already selected, evicting the oldest selection once at the
   * cap; removes it if it's already selected. */
  toggleDriver: (driverNumber: number) => void;
}

export function useDriverSelection(): DriverSelection {
  const [selectedDrivers, setSelectedDrivers] = useState<number[]>([]);

  const toggleDriver = (driverNumber: number) => {
    setSelectedDrivers((prev) => {
      if (prev.includes(driverNumber)) return prev.filter((d) => d !== driverNumber);
      if (prev.length >= MAX_SELECTED_DRIVERS) return [...prev.slice(1), driverNumber];
      return [...prev, driverNumber];
    });
  };

  return { selectedDrivers, toggleDriver };
}
