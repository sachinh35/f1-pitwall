import React, { useMemo, memo, useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceArea, ReferenceDot, TooltipProps } from 'recharts';
import { Box, Typography, Chip, IconButton, Stack, Button, Tooltip as MuiTooltip } from '@mui/material';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { LapData, Stint, RaceControlEvent } from '../services/api';
import { EnrichedF1SessionResult } from '../types';
import { processLapDataForChart } from '../utils/chartDataProcessing';
import { formatLapDuration } from '../utils/formatting';
import { getDriverColor } from '../constants/chartColors';
import { getCompoundIconUrl } from '../constants/compoundColors';

interface LapComparisonChartProps {
    lapData: LapData[];
    selectedDrivers: number[];
    sessionResults: EnrichedF1SessionResult[];
    stints: Stint[];
    raceControlEvents: RaceControlEvent[];
}

interface DriverInfo {
    driverNumber: number;
    name: string;
    color: string;
}

type ChartTooltipPayloadEntry = NonNullable<TooltipProps<number, string>['payload']>[number];

export interface CustomTooltipProps extends TooltipProps<number, string> {
    driverInfo: DriverInfo[];
}

// Custom tooltip component to show pit out lap info and compound. Exported (only) so it can be
// unit-tested directly - recharts only ever renders it in response to its own internal mouse
// hit-testing, which real browsers perform via actual layout and jsdom cannot reproduce.
export const CustomTooltip = ({ active, payload, label, driverInfo }: CustomTooltipProps) => {
    if (active && payload && payload.length) {
        return (
            <Box
                sx={{
                    backgroundColor: '#1A1A1A',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    borderRadius: '8px',
                    padding: '12px',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)',
                }}
            >
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1, color: '#FFFFFF' }}>
                    {label}
                </Typography>
                {payload.map((entry: ChartTooltipPayloadEntry) => {
                    const driverNum = parseInt(String(entry.dataKey).replace('driver_', '').replace('_pit_out', ''));
                    const driverInfo_entry = driverInfo.find((d: DriverInfo) => d.driverNumber === driverNum);
                    const driverName = driverInfo_entry?.name || `Driver ${driverNum}`;
                    const value = entry.value;
                    const isPitOutLap = entry.payload[`driver_${driverNum}_pit_out`] || false;
                    const compound = entry.payload[`driver_${driverNum}_compound`] || null;
                    const tyreAge = entry.payload[`driver_${driverNum}_tyre_age`] as number | null | undefined;
                    const isScrubSet = Boolean(entry.payload[`driver_${driverNum}_is_scrub_set`]);

                    if (value === null || value === undefined) {
                        return (
                            <Typography key={`${entry.dataKey}-na-${label}`} variant="body2" sx={{ color: 'rgba(255, 255, 255, 0.7)', mb: 0.5 }}>
                                {driverName}: N/A
                            </Typography>
                        );
                    }

                    return (
                        <Box key={`${entry.dataKey}-${label}`} sx={{ mb: 0.5 }}>
                            <Box
                                sx={{
                                    color: entry.color,
                                    fontWeight: 500,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 1,
                                    fontSize: '0.875rem',
                                }}
                            >
                                <Typography
                                    component="span"
                                    variant="body2"
                                    sx={{
                                        color: entry.color,
                                        fontWeight: 500,
                                    }}
                                >
                                    {driverName}: {formatLapDuration(value)}
                                    {typeof tyreAge === 'number' && (
                                        <Typography
                                            component="span"
                                            variant="body2"
                                            sx={{
                                                ml: 0.75,
                                                fontSize: '0.75rem',
                                                color: 'rgba(255,255,255,0.7)',
                                            }}
                                        >
                                            ({tyreAge} lap{tyreAge === 1 ? '' : 's'} on tyre)
                                        </Typography>
                                    )}
                                </Typography>
                                {isPitOutLap && (
                                    <Chip
                                        label="Pit Out"
                                        size="small"
                                        sx={{
                                            height: 18,
                                            fontSize: '0.65rem',
                                            backgroundColor: 'rgba(255, 193, 7, 0.2)',
                                            color: '#FFC107',
                                            border: '1px solid rgba(255, 193, 7, 0.4)',
                                        }}
                                    />
                                )}
                                {compound && (() => {
                                    const iconUrl = getCompoundIconUrl(compound);
                                    if (!iconUrl) return null;
                                    return (
                                        <Box
                                            component="img"
                                            src={iconUrl}
                                            alt={`${String(compound).toUpperCase()} tire`}
                                            sx={{
                                                width: 22,
                                                height: 22,
                                                maxWidth: 24,
                                                maxHeight: 24,
                                                objectFit: 'contain',
                                                display: 'inline-block',
                                                ml: 0.5,
                                                filter: 'drop-shadow(0 0 2px rgba(0,0,0,0.6))',
                                            }}
                                        />
                                    );
                                })()}
                                {isScrubSet && (
                                    <Chip
                                        label="Scrub set"
                                        size="small"
                                        sx={{
                                            height: 18,
                                            fontSize: '0.65rem',
                                            backgroundColor: 'rgba(144, 202, 249, 0.16)',
                                            color: 'rgba(187, 222, 251, 0.9)',
                                            border: '1px solid rgba(144, 202, 249, 0.4)',
                                            ml: 0.5,
                                        }}
                                    />
                                )}
                            </Box>
                        </Box>
                    );
                })}
            </Box>
        );
    }
    return null;
};

/** Recharts itself types dot/shape render-prop callbacks as `(props: any) => ReactElement`
 * (see LineDot in its own type definitions) - this is the shape this codebase actually reads
 * out of that `any`, not a full recharts-provided type. */
interface ChartDotRenderProps {
    cx?: number;
    cy?: number;
    payload?: Record<string, unknown> & { lapNumber?: number };
    index?: number;
}

// Custom dot renderer. Reserve ring only for pit-out. No compound ring.
const renderPitOutDot = (driverNumber: number, driverColor: string) => (props: ChartDotRenderProps) => {
    const { cx, cy, payload, index } = props;
    const isPitOutLap = payload?.[`driver_${driverNumber}_pit_out`] || false;
    const lapNumber = payload?.lapNumber || index;

    if (!cx || !cy) {
        return <g key={`dot-empty-${driverNumber}-${lapNumber}`}></g>;
    }

    return (
        <g key={`dot-${driverNumber}-${lapNumber}`}>
            <circle
                cx={cx}
                cy={cy}
                r={isPitOutLap ? 5 : 3}
                fill={driverColor}
                stroke={isPitOutLap ? '#FFC107' : driverColor}
                strokeWidth={isPitOutLap ? 2 : 1}
            />
            {isPitOutLap && (
                <circle
                    cx={cx}
                    cy={cy}
                    r={7}
                    fill="none"
                    stroke="#FFC107"
                    strokeWidth={1}
                    opacity={0.5}
                />
            )}
        </g>
    );
};

// Helper function to map race control events to laps
const mapEventsToLaps = (
    events: RaceControlEvent[],
    lapData: LapData[],
    selectedDrivers: number[]
): Map<number, RaceControlEvent[]> => {
    const lapToEvents = new Map<number, RaceControlEvent[]>();

    if (!events.length || !lapData.length) return lapToEvents;

    // Create a map of lap number to date_start for each driver
    const lapDateMap = new Map<number, Date>();
    lapData.forEach(lap => {
        if (lap.date_start && !lapDateMap.has(lap.lap_number)) {
            lapDateMap.set(lap.lap_number, new Date(lap.date_start));
        }
    });

    events.forEach(event => {
        const eventDate = new Date(event.date);

        // Find the lap this event belongs to
        let matchedLap: number | null = null;
        let minTimeDiff = Infinity;

        lapDateMap.forEach((lapDate, lapNum) => {
            const timeDiff = Math.abs(eventDate.getTime() - lapDate.getTime());
            // Match to the closest lap within 5 minutes (300000ms)
            if (timeDiff < minTimeDiff && timeDiff < 300000) {
                minTimeDiff = timeDiff;
                matchedLap = lapNum;
            }
        });

        if (matchedLap !== null) {
            // Filter events based on scope
            const isDriverSpecific = event.scope === 'Driver' && event.driver_number !== null;
            const isCommonEvent = event.scope === 'Track' || event.scope === 'Sector' || !event.scope;

            // Show driver-specific events only if driver is selected
            // Show common events always
            if ((isDriverSpecific && selectedDrivers.includes(event.driver_number!)) || isCommonEvent) {
                if (!lapToEvents.has(matchedLap)) {
                    lapToEvents.set(matchedLap, []);
                }
                lapToEvents.get(matchedLap)!.push(event);
            }
        }
    });

    return lapToEvents;
};

const LapComparisonChart: React.FC<LapComparisonChartProps> = ({
    lapData,
    selectedDrivers,
    sessionResults,
    stints,
    raceControlEvents,
}) => {
    // Zoom state
    const [xAxisRange, setXAxisRange] = useState<[number, number] | undefined>(undefined);
    const [yAxisDomain, setYAxisDomain] = useState<[number, number] | undefined>(undefined);
    // Drag-to-zoom selection state
    const [selectionStartIndex, setSelectionStartIndex] = useState<number | null>(null);
    const [selectionEndIndex, setSelectionEndIndex] = useState<number | null>(null);
    const [isSelecting, setIsSelecting] = useState<boolean>(false);

    // Process data for chart
    const { data: chartData } = useMemo(() => {
        return processLapDataForChart(lapData, selectedDrivers, sessionResults, stints);
    }, [lapData, selectedDrivers, sessionResults, stints]);

    // Get driver info for legend
    const driverInfo = useMemo(() => {
        return selectedDrivers.map((driverNum, index) => {
            const result = sessionResults.find(r => r.driver_number === driverNum);
            return {
                driverNumber: driverNum,
                name: result?.full_name || `Driver ${driverNum}`,
                color: getDriverColor(driverNum, index),
            };
        });
    }, [selectedDrivers, sessionResults]);

    // Calculate auto Y-axis domain from currently visible data (Brush-controlled)
    const autoYAxisRange = useMemo(() => {
        if (!chartData || chartData.length === 0) return [0, 100];

        const startIndex = xAxisRange ? Math.max(0, xAxisRange[0]) : 0;
        const endIndex = xAxisRange ? Math.min(chartData.length - 1, xAxisRange[1]) : chartData.length - 1;

        const visibleValues: number[] = [];
        for (let i = startIndex; i <= endIndex; i++) {
            const point = chartData[i];
            selectedDrivers.forEach((driverNum) => {
                const value = point[`driver_${driverNum}`];
                if (value !== null && value !== undefined && typeof value === 'number') {
                    visibleValues.push(value as number);
                }
            });
        }

        if (visibleValues.length === 0) return [0, 100];

        const min = Math.min(...visibleValues);
        const max = Math.max(...visibleValues);
        const range = max - min || 1; // avoid zero range
        const padding = Math.max(range * 0.1, 0.05); // 10% padding, minimum small padding

        return [Math.max(0, min - padding), max + padding] as [number, number];
    }, [chartData, selectedDrivers, xAxisRange]);

    // Reset zoom
    const handleResetZoom = useCallback(() => {
        setXAxisRange(undefined);
        setYAxisDomain(undefined);
        setSelectionStartIndex(null);
        setSelectionEndIndex(null);
        setIsSelecting(false);
    }, []);

    // Mouse drag-to-zoom handlers. Recharts passes its internal CategoricalChartState here,
    // which isn't part of its public type exports - this is the one field actually read out
    // of it (see e.g. LineChart's onMouseDown/onMouseMove typed as `(state, event: any) => void`
    // in recharts' own generateCategoricalChart.d.ts).
    const handleMouseDown = useCallback((e: { activeTooltipIndex?: number } | null) => {
        if (e && e.activeTooltipIndex != null) {
            setIsSelecting(true);
            setSelectionStartIndex(e.activeTooltipIndex);
            setSelectionEndIndex(e.activeTooltipIndex);
        }
    }, []);

    const handleMouseMove = useCallback((e: { activeTooltipIndex?: number } | null) => {
        if (!isSelecting) return;
        if (e && e.activeTooltipIndex != null) {
            setSelectionEndIndex(e.activeTooltipIndex);
        }
    }, [isSelecting]);

    const finalizeSelection = useCallback(() => {
        if (isSelecting && selectionStartIndex != null && selectionEndIndex != null) {
            const start = Math.min(selectionStartIndex, selectionEndIndex);
            const end = Math.max(selectionStartIndex, selectionEndIndex);
            if (end > start) {
                setXAxisRange([start, end]);
            }
        }
        setIsSelecting(false);
        setSelectionStartIndex(null);
        setSelectionEndIndex(null);
    }, [isSelecting, selectionStartIndex, selectionEndIndex]);

    const handleMouseUp = useCallback(() => {
        finalizeSelection();
    }, [finalizeSelection]);

    const handleMouseLeave = useCallback(() => {
        // Cancel selection if user leaves chart area
        if (isSelecting) {
            finalizeSelection();
        }
    }, [isSelecting, finalizeSelection]);


    // Zoom in/out functions
    const handleZoomIn = useCallback(() => {
        if (yAxisDomain) {
            const [min, max] = yAxisDomain;
            const range = max - min;
            const center = (min + max) / 2;
            const newRange = range * 0.7; // Zoom in by 30%
            setYAxisDomain([center - newRange / 2, center + newRange / 2]);
        } else {
            const [min, max] = autoYAxisRange;
            const range = max - min;
            const center = (min + max) / 2;
            const newRange = range * 0.7;
            setYAxisDomain([center - newRange / 2, center + newRange / 2]);
        }
    }, [yAxisDomain, autoYAxisRange]);

    const handleZoomOut = useCallback(() => {
        if (yAxisDomain) {
            const [min, max] = yAxisDomain;
            const range = max - min;
            const center = (min + max) / 2;
            const newRange = range * 1.4; // Zoom out by 40%
            setYAxisDomain([center - newRange / 2, center + newRange / 2]);
        } else {
            const [min, max] = autoYAxisRange;
            const range = max - min;
            const center = (min + max) / 2;
            const newRange = range * 1.4;
            setYAxisDomain([center - newRange / 2, center + newRange / 2]);
        }
    }, [yAxisDomain, autoYAxisRange]);

    // Map race control events to laps
    const eventsByLap = useMemo(() => {
        return mapEventsToLaps(raceControlEvents, lapData, selectedDrivers);
    }, [raceControlEvents, lapData, selectedDrivers]);

    // Slice data when a range is selected
    const displayedChartData = useMemo(() => {
        if (!chartData) return [];
        if (!xAxisRange) return chartData;
        const start = Math.max(0, xAxisRange[0]);
        const end = Math.min(chartData.length - 1, xAxisRange[1]);
        return chartData.slice(start, end + 1);
    }, [chartData, xAxisRange]);

    return (
        <Box sx={{ width: '100%' }}>
            {/* Zoom Controls */}
            <Stack
                direction="row"
                spacing={1}
                sx={{ alignItems: 'center', mb: 2, justifyContent: 'flex-end' }}
            >
                <Typography variant="body2" sx={{ color: 'text.secondary', mr: 1 }}>
                    Zoom:
                </Typography>
                <IconButton
                    size="small"
                    onClick={handleZoomIn}
                    sx={{
                        color: 'text.secondary',
                        '&:hover': { color: 'primary.main' },
                    }}
                    title="Zoom In (Y-axis)"
                >
                    <ZoomInIcon fontSize="small" />
                </IconButton>
                <IconButton
                    size="small"
                    onClick={handleZoomOut}
                    sx={{
                        color: 'text.secondary',
                        '&:hover': { color: 'primary.main' },
                    }}
                    title="Zoom Out (Y-axis)"
                >
                    <ZoomOutIcon fontSize="small" />
                </IconButton>
                <Button
                    size="small"
                    startIcon={<RestartAltIcon />}
                    onClick={handleResetZoom}
                    sx={{
                        color: 'text.secondary',
                        '&:hover': { color: 'primary.main' },
                        textTransform: 'none',
                    }}
                >
                    Reset
                </Button>
            </Stack>

            <Box sx={{ width: '100%', height: 500 }}>
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                        data={displayedChartData}
                        margin={{ top: 35, right: 30, left: 130, bottom: 60 }}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={handleMouseLeave}
                    >
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.1)" />
                        <XAxis
                            dataKey="lap"
                            stroke="rgba(255, 255, 255, 0.7)"
                            style={{ fontSize: '12px' }}
                        />
                        <YAxis
                            stroke="rgba(255, 255, 255, 0.7)"
                            style={{ fontSize: '12px' }}
                            width={90}
                            domain={yAxisDomain || autoYAxisRange}
                            label={{
                                value: 'Lap Duration (min:sec)',
                                angle: -90,
                                position: 'left',
                                offset: -100,
                                style: {
                                    fill: 'rgba(255, 255, 255, 0.9)',
                                    fontSize: '12px',
                                    fontStyle: 'italic',
                                    fontWeight: 700,
                                    textAnchor: 'middle',
                                },
                            }}
                            tickFormatter={(value: number) => {
                                return formatLapDuration(value);
                            }}
                        />
                        <YAxis yAxisId="raceControl" hide domain={[0, 1]} />

                        {displayedChartData.map((dataPoint) => {
                            const lapNum = dataPoint.lapNumber as number;
                            const events = eventsByLap.get(lapNum) || [];
                            if (events.length === 0) return null;

                            // Get the most significant event for the indicator
                            const getPrimaryEvent = () => {
                                // Priority: RED > Safety > YELLOW > GREEN > Other
                                const redEvent = events.find(e => e.flag === 'RED');
                                if (redEvent) return redEvent;
                                const safetyEvent = events.find(e => e.category === 'Safety');
                                if (safetyEvent) return safetyEvent;
                                const yellowEvent = events.find(e => e.flag === 'YELLOW');
                                if (yellowEvent) return yellowEvent;
                                const greenEvent = events.find(e => e.flag === 'GREEN');
                                if (greenEvent) return greenEvent;
                                return events[0];
                            };

                            const primaryEvent = getPrimaryEvent();

                            const getEventColor = () => {
                                if (primaryEvent.flag === 'YELLOW') return '#FFC107';
                                if (primaryEvent.flag === 'RED') return '#F44336';
                                if (primaryEvent.flag === 'GREEN') return '#4CAF50';
                                if (primaryEvent.category === 'Safety') return '#FF9800';
                                return '#90CAF9';
                            };

                            // Group events by type for better organization
                            const groupedEvents = {
                                flags: events.filter(e => e.flag),
                                safety: events.filter(e => e.category === 'Safety' && !e.flag),
                                other: events.filter(e => !e.flag && e.category !== 'Safety'),
                            };

                            const getFlagIcon = (flag: string | null) => {
                                switch (flag?.toUpperCase()) {
                                    case 'RED': return '🔴';
                                    case 'YELLOW': return '🟡';
                                    case 'DOUBLE YELLOW': return '🟡🟡';
                                    case 'GREEN': return '🟢';
                                    case 'CLEAR': return '✅';
                                    default: return '⚡';
                                }
                            };

                            const eventTooltipContent = (
                                <Box
                                    sx={{
                                        p: 2,
                                        minWidth: 280,
                                        maxWidth: 400,
                                        backgroundColor: 'rgba(26, 26, 26, 0.98)',
                                        border: '1px solid rgba(255, 255, 255, 0.12)',
                                        borderRadius: '12px',
                                        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
                                        backdropFilter: 'blur(10px)',
                                    }}
                                >
                                    <Typography
                                        variant="subtitle2"
                                        sx={{
                                            fontWeight: 700,
                                            mb: 1.5,
                                            color: '#FFFFFF',
                                            fontSize: '0.95rem',
                                            letterSpacing: '0.5px',
                                        }}
                                    >
                                        Lap {lapNum}
                                        <Typography
                                            component="span"
                                            sx={{
                                                ml: 1,
                                                color: 'rgba(255, 255, 255, 0.6)',
                                                fontWeight: 500,
                                                fontSize: '0.85rem',
                                            }}
                                        >
                                            • {events.length} event{events.length > 1 ? 's' : ''}
                                        </Typography>
                                    </Typography>

                                    {/* Flags Section */}
                                    {groupedEvents.flags.length > 0 && (
                                        <Box sx={{ mb: 1.5 }}>
                                            <Typography
                                                variant="caption"
                                                sx={{
                                                    color: 'rgba(255, 255, 255, 0.5)',
                                                    fontSize: '0.7rem',
                                                    textTransform: 'uppercase',
                                                    letterSpacing: '1px',
                                                    mb: 0.75,
                                                    display: 'block',
                                                }}
                                            >
                                                Flags
                                            </Typography>
                                            {groupedEvents.flags.map((event, eventIdx) => (
                                                <Box
                                                    key={`flag-${eventIdx}`}
                                                    sx={{
                                                        mb: 0.75,
                                                        display: 'flex',
                                                        alignItems: 'flex-start',
                                                        gap: 1,
                                                    }}
                                                >
                                                    <Typography sx={{ fontSize: '0.9rem', lineHeight: 1.2 }}>
                                                        {getFlagIcon(event.flag)}
                                                    </Typography>
                                                    <Typography
                                                        variant="body2"
                                                        sx={{
                                                            color: 'rgba(255, 255, 255, 0.95)',
                                                            fontSize: '0.8rem',
                                                            lineHeight: 1.4,
                                                            flex: 1,
                                                        }}
                                                    >
                                                        {event.message}
                                                    </Typography>
                                                </Box>
                                            ))}
                                        </Box>
                                    )}

                                    {/* Safety Section */}
                                    {groupedEvents.safety.length > 0 && (
                                        <Box sx={{ mb: 1.5 }}>
                                            <Typography
                                                variant="caption"
                                                sx={{
                                                    color: 'rgba(255, 255, 255, 0.5)',
                                                    fontSize: '0.7rem',
                                                    textTransform: 'uppercase',
                                                    letterSpacing: '1px',
                                                    mb: 0.75,
                                                    display: 'block',
                                                }}
                                            >
                                                Safety
                                            </Typography>
                                            {groupedEvents.safety.map((event, eventIdx) => (
                                                <Box
                                                    key={`safety-${eventIdx}`}
                                                    sx={{
                                                        mb: 0.75,
                                                        display: 'flex',
                                                        alignItems: 'flex-start',
                                                        gap: 1,
                                                    }}
                                                >
                                                    <Typography sx={{ fontSize: '0.9rem', lineHeight: 1.2 }}>
                                                        🚨
                                                    </Typography>
                                                    <Typography
                                                        variant="body2"
                                                        sx={{
                                                            color: 'rgba(255, 255, 255, 0.95)',
                                                            fontSize: '0.8rem',
                                                            lineHeight: 1.4,
                                                            flex: 1,
                                                        }}
                                                    >
                                                        {event.message}
                                                    </Typography>
                                                </Box>
                                            ))}
                                        </Box>
                                    )}

                                    {/* Other Events Section */}
                                    {groupedEvents.other.length > 0 && (
                                        <Box>
                                            <Typography
                                                variant="caption"
                                                sx={{
                                                    color: 'rgba(255, 255, 255, 0.5)',
                                                    fontSize: '0.7rem',
                                                    textTransform: 'uppercase',
                                                    letterSpacing: '1px',
                                                    mb: 0.75,
                                                    display: 'block',
                                                }}
                                            >
                                                Other
                                            </Typography>
                                            {groupedEvents.other.map((event, eventIdx) => (
                                                <Box
                                                    key={`other-${eventIdx}`}
                                                    sx={{
                                                        mb: 0.75,
                                                        display: 'flex',
                                                        alignItems: 'flex-start',
                                                        gap: 1,
                                                    }}
                                                >
                                                    <Typography sx={{ fontSize: '0.9rem', lineHeight: 1.2 }}>
                                                        ⚡
                                                    </Typography>
                                                    <Typography
                                                        variant="body2"
                                                        sx={{
                                                            color: 'rgba(255, 255, 255, 0.95)',
                                                            fontSize: '0.8rem',
                                                            lineHeight: 1.4,
                                                            flex: 1,
                                                        }}
                                                    >
                                                        {event.message}
                                                    </Typography>
                                                </Box>
                                            ))}
                                        </Box>
                                    )}
                                </Box>
                            );

                            return (
                                <ReferenceDot
                                    key={`event-dot-${lapNum}`}
                                    x={dataPoint.lap as string}
                                    y={1}
                                    yAxisId="raceControl"
                                    shape={(props: { cx?: number; cy?: number }) => {
                                        const { cx, cy } = props;
                                        return (
                                            <foreignObject x={(cx ?? 0) - 10} y={(cy ?? 0) - 10} width={20} height={20} style={{ overflow: 'visible' }}>
                                                <MuiTooltip
                                                    title={eventTooltipContent}
                                                    arrow
                                                    placement="top"
                                                    slotProps={{
                                                        tooltip: {
                                                            sx: {
                                                                backgroundColor: 'transparent',
                                                                padding: 0,
                                                                maxWidth: 'none',
                                                            },
                                                        },
                                                        arrow: {
                                                            sx: {
                                                                color: 'rgba(26, 26, 26, 0.98)',
                                                            },
                                                        },
                                                    }}
                                                >
                                                    <Box
                                                        sx={{
                                                            width: 10,
                                                            height: 10,
                                                            borderRadius: '50%',
                                                            backgroundColor: getEventColor(),
                                                            border: '2px solid rgba(255, 255, 255, 0.4)',
                                                            boxShadow: `0 0 10px ${getEventColor()}, 0 2px 4px rgba(0, 0, 0, 0.3)`,
                                                            transition: 'all 0.2s ease',
                                                            cursor: 'pointer',
                                                            margin: '5px', // Center in 20x20 box
                                                            '&:hover': {
                                                                transform: 'scale(1.4)',
                                                                boxShadow: `0 0 16px ${getEventColor()}, 0 4px 8px rgba(0, 0, 0, 0.4)`,
                                                                border: '2px solid rgba(255, 255, 255, 0.6)',
                                                            },
                                                        }}
                                                    />
                                                </MuiTooltip>
                                            </foreignObject>
                                        );
                                    }}
                                />
                            );
                        })}
                        <Tooltip content={(props: TooltipProps<number, string>) => <CustomTooltip {...props} driverInfo={driverInfo} />} />
                        <Legend
                            wrapperStyle={{ paddingTop: '20px' }}
                            formatter={(value: string) => {
                                const driverNum = parseInt(value.replace('driver_', ''));
                                const info = driverInfo.find(d => d.driverNumber === driverNum);
                                return info ? `#${info.driverNumber} ${info.name}` : value;
                            }}
                        />
                        {driverInfo.map((driver) => (
                            <Line
                                key={`line-${driver.driverNumber}`}
                                type="monotone"
                                dataKey={`driver_${driver.driverNumber}`}
                                stroke={driver.color}
                                strokeWidth={2}
                                dot={renderPitOutDot(driver.driverNumber, driver.color)}
                                activeDot={{ r: 6 }}
                                name={`driver_${driver.driverNumber}`}
                                connectNulls={false}
                            />
                        ))}
                        {isSelecting && selectionStartIndex != null && selectionEndIndex != null && (() => {
                            const start = Math.min(selectionStartIndex, selectionEndIndex);
                            const end = Math.max(selectionStartIndex, selectionEndIndex);
                            const x1 = (chartData[start]?.lap ?? '') as string | number;
                            const x2 = (chartData[end]?.lap ?? '') as string | number;
                            return (
                                <ReferenceArea
                                    // Use labels from the full chartData for selection band
                                    x1={x1}
                                    x2={x2}
                                    y1={autoYAxisRange[0]}
                                    y2={autoYAxisRange[1]}
                                    stroke="rgba(225, 6, 0, 0.6)"
                                    strokeOpacity={0.3}
                                    fill="rgba(225, 6, 0, 0.15)"
                                />
                            );
                        })()}
                    </LineChart>
                </ResponsiveContainer>
            </Box>

            {/* Instructions */}
            <Typography variant="caption" sx={{ color: 'text.secondary', mt: 1, display: 'block' }}>
                💡 Tip: Click and drag on the chart to select a lap window (X-axis). Use the buttons above to adjust the time window (Y-axis).
            </Typography>
        </Box>
    );
};

// Memoize the chart component to prevent unnecessary re-renders
export default memo(LapComparisonChart);

