/**
 * Utility functions for formatting data
 */

export const formatDuration = (seconds: number | null | string): string => {
    if (seconds === null || typeof seconds === 'string') {
        return '';
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.round((seconds - Math.floor(seconds)) * 1000);

    return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
};

/**
 * Format lap duration for chart display (min:sec.millis)
 */
export const formatLapDuration = (value: number): string => {
    if (value === null || value === undefined) return '';
    const minutes = Math.floor(value / 60);
    const seconds = (value % 60).toFixed(3);
    return `${minutes}:${seconds.padStart(6, '0')}`;
};

