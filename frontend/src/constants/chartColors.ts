/**
 * Chart color constants for driver comparison lines
 */

export const DRIVER_COLORS = [
    '#E10600', // F1 Red
    '#1E41FF', // Blue
    '#00D2BE', // Cyan
    '#FF8700', // Orange
    '#FFF500', // Yellow
    '#006F62', // Dark Green
    '#900000', // Dark Red
    '#2B4562', // Dark Blue
    '#DC143C', // Crimson
    '#50C878', // Emerald
    '#FF1493', // Deep Pink
    '#00CED1', // Dark Turquoise
    '#FFD700', // Gold
    '#8A2BE2', // Blue Violet
    '#FF6347', // Tomato
    '#20B2AA', // Light Sea Green
    '#FF69B4', // Hot Pink
    '#32CD32', // Lime Green
    '#FF4500', // Orange Red
    '#9370DB', // Medium Purple
];

export const getDriverColor = (_driverNumber: number, index: number): string => {
    // Use modulo to cycle through colors if we have more drivers than colors
    return DRIVER_COLORS[index % DRIVER_COLORS.length];
};

