import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router';
import { isAxiosError } from 'axios';
import { getYears, getRacesForYear, getSessionResults, getSessionLapData, getSessionStints, getSessionRaceControlEvents, LapData, Stint, RaceControlEvent, startLiveStream, startSimulation, attachLiveStream, getF1TvTokenStatus, ConfirmedRosterEntry } from '../services/api';
import {
    Box,
    Grid,
    Typography,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    Table,
    TableContainer,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    SelectChangeEvent,
    FormGroup,
    FormControlLabel,
    Checkbox,
    Menu,
    IconButton,
    Card,
    CardContent,
    Stack,
    Chip,
    Divider,
    CircularProgress,
    Button,
    Alert,
    Snackbar
} from '@mui/material';
import TuneIcon from '@mui/icons-material/Tune';
import EmojiFlagsIcon from '@mui/icons-material/EmojiFlags';
import CalendarTodayIcon from '@mui/icons-material/CalendarToday';
import SportsMotorsportsIcon from '@mui/icons-material/SportsMotorsports';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import LiveTvIcon from '@mui/icons-material/LiveTv';
import LapComparisonChart from './LapComparisonChart';
import ConfirmRosterDialog from './ConfirmRosterDialog';
import UpdateTokenDialog from './UpdateTokenDialog';
import { Race, EnrichedF1SessionResult } from '../types';
import { formatDuration } from '../utils/formatting';
import { getCountryFlagEmoji, getCountryName } from '../utils/countryMapping';
import { mergeLapData } from '../utils/chartDataProcessing';

const Dashboard = () => {
    const [years, setYears] = useState<number[]>([]);
    const [selectedYear, setSelectedYear] = useState<number | string>('');
    const [races, setRaces] = useState<Race[]>([]);
    const [locations, setLocations] = useState<string[]>([]);
    const [locationCountryMap, setLocationCountryMap] = useState<Map<string, string>>(new Map());
    const [selectedLocation, setSelectedLocation] = useState<string>('');
    // Fully derivable from races/selectedLocation - no need to sync it into its own state via
    // an effect (see the effect below, which used to do exactly that).
    const sessions = useMemo(
        () => races.filter((race) => race.location === selectedLocation),
        [races, selectedLocation]
    );
    const [selectedSessionKey, setSelectedSessionKey] = useState<number | null>(null);
    const [sessionResults, setSessionResults] = useState<EnrichedF1SessionResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedDrivers, setSelectedDrivers] = useState<Set<number>>(new Set());
    const [lapData, setLapData] = useState<LapData[]>([]);
    const [loadingLapData, setLoadingLapData] = useState<Set<number>>(new Set());
    const [stints, setStints] = useState<Stint[]>([]);
    const [raceControlEvents, setRaceControlEvents] = useState<RaceControlEvent[]>([]);
    // Cache to track which drivers' lap data we've already fetched
    const fetchedDriversRef = useRef<Set<number>>(new Set());
    const [columnVisibility, setColumnVisibility] = useState({
        laps: true,
        gapToLeader: true,
        dnf: true,
        dns: true,
        dsq: true,
    });
    const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
    const [streaming, setStreaming] = useState(false);
    const [streamingLoading, setStreamingLoading] = useState(false);
    const [streamMessage, setStreamMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const [rosterDialogOpen, setRosterDialogOpen] = useState(false);
    const [rosterDialogAction, setRosterDialogAction] = useState<'live' | 'simulate' | 'attach' | null>(null);
    const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
    const [tokenDialogReason, setTokenDialogReason] = useState<string | null>(null);
    const [pendingConfirmedRoster, setPendingConfirmedRoster] = useState<ConfirmedRosterEntry[] | null>(null);

    const navigate = useNavigate();

    const handleSettingsClick = (event: React.MouseEvent<HTMLButtonElement>) => {
        setAnchorEl(event.currentTarget);
    };

    const handleSettingsClose = () => {
        setAnchorEl(null);
    };

    const handleStartLiveStream = () => {
        setRosterDialogAction('live');
        setRosterDialogOpen(true);
    };

    const handleStartSimulation = () => {
        setRosterDialogAction('simulate');
        setRosterDialogOpen(true);
    };

    const handleAttachLiveStream = () => {
        setRosterDialogAction('attach');
        setRosterDialogOpen(true);
    };

    const handleRosterDialogClose = () => {
        setRosterDialogOpen(false);
        setRosterDialogAction(null);
    };

    const runStartLiveStream = async (confirmedRoster: ConfirmedRosterEntry[]) => {
        try {
            setStreamingLoading(true);
            setStreamMessage(null);

            // Step 1: Start the stream on the backend (backend handles auth using saved token)
            const response = await startLiveStream(undefined, undefined, undefined, confirmedRoster);

            setStreaming(true);
            setStreamMessage({
                type: 'success',
                text: `Live stream started! Stream ID: ${response.stream_id}. Log file: ${response.log_file}`
            });

            // Redirect to live stream page
            navigate(`/live-stream/${response.stream_id}`);

        } catch (error) {
            console.error('Error starting live stream:', error);
            let errorMessage = 'Failed to start live stream.';

            if (isAxiosError(error)) {
                if (error.response?.status === 400 || error.response?.status === 401) {
                    errorMessage = 'Authentication required. Please run "uv run python auth_helper.py" in the backend directory to authenticate with F1 TV Pro.';
                } else if (error.response?.data?.detail) {
                    errorMessage = error.response.data.detail;
                }
            } else if (error instanceof Error) {
                errorMessage = error.message;
            }

            setStreamMessage({
                type: 'error',
                text: errorMessage
            });
            setStreaming(false);
        } finally {
            setStreamingLoading(false);
        }
    };

    const handleTokenValidated = () => {
        setTokenDialogOpen(false);
        const roster = pendingConfirmedRoster;
        setPendingConfirmedRoster(null);
        if (roster) {
            runStartLiveStream(roster);
        }
    };

    const handleRosterConfirmed = async (confirmedRoster: ConfirmedRosterEntry[]) => {
        const action = rosterDialogAction;
        setRosterDialogOpen(false);
        setRosterDialogAction(null);

        if (action === 'live') {
            // Gate the real live-stream path on a valid, non-expired F1TV token - a
            // missing/expired token used to fail silently (CarData.z/Position.z just
            // never showed up, no error anywhere). Simulate/attach don't need this:
            // simulate replays a saved log, attach hooks into an already-running
            // capture that handles its own token separately.
            let status;
            try {
                status = await getF1TvTokenStatus();
            } catch (error) {
                console.error('Error checking F1TV token status:', error);
                setStreamMessage({ type: 'error', text: 'Failed to check F1TV token status. Please try again.' });
                return;
            }

            if (!status.valid) {
                setPendingConfirmedRoster(confirmedRoster);
                setTokenDialogReason(status.reason ?? null);
                setTokenDialogOpen(true);
                return;
            }

            await runStartLiveStream(confirmedRoster);
        } else if (action === 'simulate') {
            try {
                setStreamingLoading(true);
                const response = await startSimulation({ confirmed_roster: confirmedRoster });
                setStreaming(true);
                navigate(`/live-stream/${response.stream_id}`);
            } catch (error) {
                console.error('Error starting simulation:', error);
                setStreamMessage({
                    type: 'error',
                    text: 'Failed to start simulation'
                });
            } finally {
                setStreamingLoading(false);
            }
        } else if (action === 'attach') {
            try {
                setStreamingLoading(true);
                setStreamMessage(null);

                // Attaches to the standalone capture process (scripts/capture_stream.py) by
                // tailing its raw jsonl file, instead of opening a second SignalR connection -
                // the capture keeps running independent of this backend/frontend, so this is
                // safe to call again any time (after a backend restart, a page reload, etc.)
                // and it just catches straight back up.
                const response = await attachLiveStream(undefined, confirmedRoster);

                setStreaming(true);
                setStreamMessage({
                    type: 'success',
                    text: `Attached to live capture! Stream ID: ${response.stream_id}. Log file: ${response.log_file}`
                });

                navigate(`/live-stream/${response.stream_id}`);

            } catch (error) {
                console.error('Error attaching to live capture:', error);
                let errorMessage = 'Failed to attach to live capture.';

                if (isAxiosError(error) && error.response?.status === 404) {
                    errorMessage = 'No live capture found. Start it from a terminal first: ./scripts/run_capture.sh <session-name>';
                } else if (isAxiosError(error) && error.response?.data?.detail) {
                    errorMessage = error.response.data.detail;
                } else if (error instanceof Error) {
                    errorMessage = error.message;
                }

                setStreamMessage({ type: 'error', text: errorMessage });
                setStreaming(false);
            } finally {
                setStreamingLoading(false);
            }
        }
    };

    const handleCloseSnackbar = () => {
        setStreamMessage(null);
    };

    const handleColumnVisibilityChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        setColumnVisibility({
            ...columnVisibility,
            [event.target.name]: event.target.checked,
        });
    };

    useEffect(() => {
        const fetchYears = async () => {
            const data = await getYears();
            setYears(data);
        };
        fetchYears();
    }, []);

    useEffect(() => {
        if (selectedYear) {
            const fetchRaces = async () => {
                const data = await getRacesForYear(selectedYear as number);
                setRaces(data);
                const uniqueLocations: string[] = Array.from(new Set(data.map((race: Race) => race.location)));
                // Create a map of location -> country_code (use first occurrence for each location)
                const locationToCountry = new Map<string, string>();
                data.forEach((race: Race) => {
                    if (!locationToCountry.has(race.location) && race.country_code) {
                        locationToCountry.set(race.location, race.country_code);
                    }
                });
                setLocationCountryMap(locationToCountry);
                setLocations(uniqueLocations);
                setSelectedLocation('');
                setSelectedSessionKey(null);
                setSessionResults([]);
            };
            fetchRaces();
        }
    }, [selectedYear]);

    useEffect(() => {
        if (selectedLocation) {
            // Clears the stale session selection whenever the location filter changes -
            // deliberate, not derivable (unlike `sessions` above, there's no single "correct"
            // session to select for a new location, so this has to actively clear it).
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setSelectedSessionKey(null);
            setSessionResults([]);
        }
    }, [selectedLocation]);

    useEffect(() => {
        if (selectedSessionKey) {
            const fetchSessionResults = async () => {
                setLoading(true);
                try {
                    const data = await getSessionResults(selectedSessionKey);
                    setSessionResults(data);
                    // Reset selected drivers and lap data cache when session changes
                    setSelectedDrivers(new Set());
                    setLapData([]);
                    fetchedDriversRef.current = new Set();
                    // Fetch stints for this session
                    try {
                        const stintsData = await getSessionStints(selectedSessionKey);
                        setStints(stintsData);
                    } catch (err) {
                        console.error('Error fetching stints:', err);
                        setStints([]);
                    }
                    // Fetch race control events for this session
                    try {
                        const eventsData = await getSessionRaceControlEvents(selectedSessionKey);
                        setRaceControlEvents(eventsData);
                    } catch (err) {
                        console.error('Error fetching race control events:', err);
                        setRaceControlEvents([]);
                    }
                } finally {
                    setLoading(false);
                }
            };
            fetchSessionResults();
        } else {
            // Clears everything tied to a session when the session is deselected entirely -
            // deliberate reset, not derivable.
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setSessionResults([]);
            setSelectedDrivers(new Set());
            setLapData([]);
            fetchedDriversRef.current = new Set();
            setStints([]);
            setRaceControlEvents([]);
        }
    }, [selectedSessionKey]);

    // Fetch lap data incrementally when drivers are selected/deselected
    useEffect(() => {
        if (selectedSessionKey && selectedDrivers.size > 0) {
            const fetchMissingLapData = async () => {
                // Find drivers that need data fetched
                // A driver needs fetching if:
                // 1. Not in cache, OR
                // 2. In cache but no data exists in state (was filtered out when deselected)
                const driversToFetch = Array.from(selectedDrivers).filter(driverNum => {
                    if (!fetchedDriversRef.current.has(driverNum)) {
                        // Not in cache, definitely need to fetch
                        return true;
                    }
                    // In cache, but check if data actually exists in state
                    const hasDataInState = lapData.some(lap => lap.driver_number === driverNum);
                    return !hasDataInState;
                });

                if (driversToFetch.length === 0) {
                    // All selected drivers already have data, just filter existing data
                    setLapData(prevData =>
                        prevData.filter(lap => selectedDrivers.has(lap.driver_number))
                    );
                    return;
                }

                // Set loading state for new drivers
                setLoadingLapData(prev => {
                    const newSet = new Set(prev);
                    driversToFetch.forEach(driverNum => newSet.add(driverNum));
                    return newSet;
                });

                try {
                    const newData = await getSessionLapData(selectedSessionKey, driversToFetch);

                    // Mark these drivers as fetched
                    driversToFetch.forEach(driverNum => {
                        fetchedDriversRef.current.add(driverNum);
                    });

                    // Merge new data with existing data
                    setLapData(prevData => {
                        const merged = mergeLapData(prevData, newData);
                        // Filter to only include selected drivers
                        return merged.filter(lap => selectedDrivers.has(lap.driver_number));
                    });
                } catch (error) {
                    console.error('Error fetching lap data:', error);
                    // On error, remove from cache so it can be retried
                    driversToFetch.forEach(driverNum => {
                        fetchedDriversRef.current.delete(driverNum);
                    });
                } finally {
                    setLoadingLapData(prev => {
                        const newSet = new Set(prev);
                        driversToFetch.forEach(driverNum => newSet.delete(driverNum));
                        return newSet;
                    });
                }
            };

            fetchMissingLapData();
        } else if (selectedDrivers.size === 0) {
            // No drivers selected, clear lap data and cache - deliberate reset, not derivable.
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setLapData([]);
            fetchedDriversRef.current.clear();
        } else {
            // Drivers deselected (but some remain), filter existing data
            setLapData(prevData =>
                prevData.filter(lap => selectedDrivers.has(lap.driver_number))
            );
            // Remove deselected drivers from fetched cache
            const removedDrivers = Array.from(fetchedDriversRef.current).filter(
                driverNum => !selectedDrivers.has(driverNum)
            );
            removedDrivers.forEach(driverNum => {
                fetchedDriversRef.current.delete(driverNum);
            });
        }
        // `lapData` is read above only to check per-driver cache freshness, and this effect
        // itself calls setLapData (functional form) on every run - listing it as a dependency
        // would make each of those calls re-trigger the effect on its own new array reference,
        // an infinite loop. `fetchedDriversRef` (a ref, not state) is what actually gates
        // whether a fetch happens again.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selectedSessionKey, selectedDrivers]);

    const handleDriverSelection = (driverNumber: number) => {
        setSelectedDrivers(prev => {
            const newSet = new Set(prev);
            if (newSet.has(driverNumber)) {
                newSet.delete(driverNumber);
            } else {
                newSet.add(driverNumber);
            }
            return newSet;
        });
    };

    const handleSessionChange = (event: SelectChangeEvent<string>) => {
        const sessionName = event.target.value;
        const session = sessions.find(s => s.session_name === sessionName);
        if (session) {
            setSelectedSessionKey(session.session_key);
        }
    }

    return (
        <Box sx={{
            flexGrow: 1,
            minHeight: '100vh',
            background: 'linear-gradient(180deg, #0A0A0A 0%, #0F0F0F 100%)',
            py: { xs: 3, md: 4 },
            px: { xs: 2, sm: 3, md: 4 }
        }}>
            <Box sx={{ mb: 4 }}>
                <Stack direction="row" spacing={2} sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                    <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
                        <SportsMotorsportsIcon sx={{ fontSize: 40, color: 'primary.main' }} />
                        <Typography variant="h1" component="h1">
                            F1 Dashboard
                        </Typography>
                    </Stack>
                    <Button
                        variant="contained"
                        color="primary"
                        startIcon={<LiveTvIcon />}
                        onClick={handleStartLiveStream}
                        disabled={streamingLoading || streaming}
                        sx={{
                            px: 3,
                            py: 1.5,
                            borderRadius: 2,
                            textTransform: 'none',
                            fontWeight: 600,
                            boxShadow: streaming ? '0 4px 12px rgba(225, 6, 0, 0.3)' : 'none',
                        }}
                    >
                        {streamingLoading ? (
                            <>
                                <CircularProgress size={20} sx={{ mr: 1 }} color="inherit" />
                                Starting...
                            </>
                        ) : streaming ? (
                            'Streaming Active'
                        ) : (
                            'Start Live Stream'
                        )}
                    </Button>
                    <Button
                        variant="outlined"
                        color="secondary"
                        onClick={handleStartSimulation}
                        disabled={streamingLoading || streaming}
                        sx={{
                            px: 3,
                            py: 1.5,
                            borderRadius: 2,
                            textTransform: 'none',
                            fontWeight: 600,
                            ml: 2
                        }}
                    >
                        Test Simulation
                    </Button>
                    <Button
                        variant="outlined"
                        color="primary"
                        onClick={handleAttachLiveStream}
                        disabled={streamingLoading || streaming}
                        sx={{
                            px: 3,
                            py: 1.5,
                            borderRadius: 2,
                            textTransform: 'none',
                            fontWeight: 600,
                            ml: 2
                        }}
                        title="Attach to a standalone capture process already running via scripts/run_capture.sh - the recommended way to watch a real live session"
                    >
                        Attach to Live Capture
                    </Button>
                </Stack>
                <Typography variant="body1" sx={{ color: 'text.secondary', ml: 6 }}>
                    Explore Formula 1 race results and session data
                </Typography>
            </Box>

            <ConfirmRosterDialog
                open={rosterDialogOpen}
                onClose={handleRosterDialogClose}
                onConfirm={handleRosterConfirmed}
                title={rosterDialogAction === 'simulate' ? 'Confirm Lineup for Simulation' : 'Confirm Lineup Before Going Live'}
            />

            <UpdateTokenDialog
                open={tokenDialogOpen}
                onClose={() => setTokenDialogOpen(false)}
                onValidated={handleTokenValidated}
                reason={tokenDialogReason}
            />

            <Snackbar
                open={streamMessage !== null}
                autoHideDuration={6000}
                onClose={handleCloseSnackbar}
                anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
            >
                <Alert
                    onClose={handleCloseSnackbar}
                    severity={streamMessage?.type || 'info'}
                    sx={{ width: '100%' }}
                >
                    {streamMessage?.text}
                </Alert>
            </Snackbar>

            <Grid container spacing={3} sx={{ mb: 4 }}>
                <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                    <Card elevation={0} sx={{
                        height: '100%',
                        transition: 'all 0.3s ease',
                        '&:hover': {
                            transform: 'translateY(-2px)',
                            boxShadow: '0 8px 24px rgba(225, 6, 0, 0.15)',
                        }
                    }}>
                        <CardContent>
                            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mb: 2 }}>
                                <CalendarTodayIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                                <InputLabel sx={{ fontWeight: 600, color: 'text.primary' }}>
                                    Season
                                </InputLabel>
                            </Stack>
                            <FormControl fullWidth>
                                <Select
                                    value={selectedYear || 'placeholder-year'}
                                    label="Year"
                                    onChange={(e: SelectChangeEvent<number | string>) => {
                                        if (e.target.value !== 'placeholder-year') {
                                            setSelectedYear(e.target.value as number);
                                        }
                                    }}
                                    displayEmpty
                                    sx={{
                                        '& .MuiSelect-select': {
                                            py: 1.5,
                                        }
                                    }}
                                >
                                    <MenuItem value="placeholder-year" disabled>
                                        <Typography variant="body2" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
                                            Select a season...
                                        </Typography>
                                    </MenuItem>
                                    {years.map((year) => (
                                        <MenuItem key={year} value={year}>{year}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                    <Card elevation={0} sx={{
                        height: '100%',
                        transition: 'all 0.3s ease',
                        '&:hover': {
                            transform: 'translateY(-2px)',
                            boxShadow: '0 8px 24px rgba(225, 6, 0, 0.15)',
                        }
                    }}>
                        <CardContent>
                            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mb: 2 }}>
                                <EmojiFlagsIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                                <InputLabel sx={{ fontWeight: 600, color: 'text.primary' }}>
                                    Location
                                </InputLabel>
                            </Stack>
                            <FormControl fullWidth disabled={!selectedYear}>
                                <Select
                                    value={selectedLocation || 'placeholder-location'}
                                    label="Location"
                                    onChange={(e: SelectChangeEvent<string>) => {
                                        if (e.target.value !== 'placeholder-location') {
                                            setSelectedLocation(e.target.value);
                                        }
                                    }}
                                    displayEmpty
                                    sx={{
                                        '& .MuiSelect-select': {
                                            py: 1.5,
                                        }
                                    }}
                                >
                                    <MenuItem value="placeholder-location" disabled>
                                        <Typography variant="body2" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
                                            {selectedYear ? 'Select a location...' : 'Select a Season first'}
                                        </Typography>
                                    </MenuItem>
                                    {locations.map((location) => {
                                        const countryCode = locationCountryMap.get(location);
                                        const flagEmoji = countryCode ? getCountryFlagEmoji(countryCode) : null;
                                        return (
                                            <MenuItem key={location} value={location}>
                                                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                                                    {flagEmoji && (
                                                        <Typography variant="body2" sx={{ fontSize: '1.2rem' }}>
                                                            {flagEmoji}
                                                        </Typography>
                                                    )}
                                                    <Typography variant="body2">{location}</Typography>
                                                </Stack>
                                            </MenuItem>
                                        );
                                    })}
                                </Select>
                            </FormControl>
                        </CardContent>
                    </Card>
                </Grid>
                <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                    <Card elevation={0} sx={{
                        height: '100%',
                        transition: 'all 0.3s ease',
                        '&:hover': {
                            transform: 'translateY(-2px)',
                            boxShadow: '0 8px 24px rgba(225, 6, 0, 0.15)',
                        }
                    }}>
                        <CardContent>
                            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', mb: 2 }}>
                                <SportsMotorsportsIcon sx={{ color: 'primary.main', fontSize: 20 }} />
                                <InputLabel sx={{ fontWeight: 600, color: 'text.primary' }}>
                                    Session
                                </InputLabel>
                            </Stack>
                            <FormControl fullWidth disabled={!selectedLocation}>
                                <Select
                                    value={sessions.find(s => s.session_key === selectedSessionKey)?.session_name || 'placeholder-session'}
                                    label="Session"
                                    onChange={(e: SelectChangeEvent<string>) => {
                                        if (e.target.value !== 'placeholder-session') {
                                            handleSessionChange(e);
                                        }
                                    }}
                                    displayEmpty
                                    sx={{
                                        '& .MuiSelect-select': {
                                            py: 1.5,
                                        }
                                    }}
                                >
                                    <MenuItem value="placeholder-session" disabled>
                                        <Typography variant="body2" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
                                            {selectedLocation ? 'Select a session...' : 'Select a Location first'}
                                        </Typography>
                                    </MenuItem>
                                    {sessions.map((session) => (
                                        <MenuItem key={session.session_key} value={session.session_name}>{session.session_name}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
            {sessionResults.length > 0 && (
                <Card elevation={0} sx={{ mt: 2 }}>
                    <CardContent sx={{ p: 0 }}>
                        <Box sx={{
                            p: 3,
                            pb: 2,
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            borderBottom: '1px solid',
                            borderColor: 'divider'
                        }}>
                            <Box>
                                <Typography variant="h2" component="h2" sx={{ mb: 0.5 }}>
                                    Session Results
                                </Typography>
                                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
                                    {selectedYear && (
                                        <Chip
                                            label={`${selectedYear}`}
                                            size="small"
                                            sx={{
                                                backgroundColor: 'rgba(225, 6, 0, 0.15)',
                                                color: 'primary.main',
                                                fontWeight: 600
                                            }}
                                        />
                                    )}
                                    {selectedLocation && (
                                        <Chip
                                            label={selectedLocation}
                                            size="small"
                                            sx={{
                                                backgroundColor: 'rgba(255, 255, 255, 0.08)',
                                                color: 'text.primary',
                                            }}
                                        />
                                    )}
                                    {sessions.find(s => s.session_key === selectedSessionKey)?.session_name && (
                                        <Chip
                                            label={sessions.find(s => s.session_key === selectedSessionKey)?.session_name}
                                            size="small"
                                            sx={{
                                                backgroundColor: 'rgba(255, 255, 255, 0.08)',
                                                color: 'text.primary',
                                            }}
                                        />
                                    )}
                                </Stack>
                            </Box>
                            <IconButton
                                aria-controls="settings-menu"
                                aria-haspopup="true"
                                onClick={handleSettingsClick}
                                sx={{
                                    border: '1px solid',
                                    borderColor: 'divider',
                                    '&:hover': {
                                        borderColor: 'primary.main',
                                    }
                                }}
                            >
                                <TuneIcon />
                            </IconButton>
                            <Menu
                                id="settings-menu"
                                anchorEl={anchorEl}
                                keepMounted
                                open={Boolean(anchorEl)}
                                onClose={handleSettingsClose}
                                slotProps={{
                                    paper: {
                                        sx: {
                                            mt: 1,
                                            minWidth: 200,
                                        }
                                    }
                                }}
                            >
                                <Box sx={{ p: 2 }}>
                                    <Typography variant="body2" sx={{ mb: 1.5, fontWeight: 600, color: 'text.secondary' }}>
                                        Column Visibility
                                    </Typography>
                                    <Divider sx={{ mb: 1.5 }} />
                                    <FormGroup>
                                        <FormControlLabel
                                            control={<Checkbox checked={columnVisibility.laps} onChange={handleColumnVisibilityChange} name="laps" />}
                                            label="Laps"
                                        />
                                        <FormControlLabel
                                            control={<Checkbox checked={columnVisibility.gapToLeader} onChange={handleColumnVisibilityChange} name="gapToLeader" />}
                                            label="Gap to Leader"
                                        />
                                        <FormControlLabel
                                            control={<Checkbox checked={columnVisibility.dnf} onChange={handleColumnVisibilityChange} name="dnf" />}
                                            label="DNF"
                                        />
                                        <FormControlLabel
                                            control={<Checkbox checked={columnVisibility.dns} onChange={handleColumnVisibilityChange} name="dns" />}
                                            label="DNS"
                                        />
                                        <FormControlLabel
                                            control={<Checkbox checked={columnVisibility.dsq} onChange={handleColumnVisibilityChange} name="dsq" />}
                                            label="DSQ"
                                        />
                                    </FormGroup>
                                </Box>
                            </Menu>
                        </Box>
                        {loading ? (
                            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
                                <CircularProgress size={48} />
                            </Box>
                        ) : (
                            <TableContainer>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Position</TableCell>
                                            <TableCell>Driver</TableCell>
                                            <TableCell>Nationality</TableCell>
                                            <TableCell>Driver #</TableCell>
                                            {columnVisibility.laps && <TableCell>Laps</TableCell>}
                                            <TableCell>Duration</TableCell>
                                            {columnVisibility.gapToLeader && <TableCell>Gap to Leader</TableCell>}
                                            {columnVisibility.dnf && <TableCell>DNF</TableCell>}
                                            {columnVisibility.dns && <TableCell>DNS</TableCell>}
                                            {columnVisibility.dsq && <TableCell>DSQ</TableCell>}
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {sessionResults.map((result, index) => (
                                            <TableRow
                                                key={result.driver_number}
                                                sx={{
                                                    '&:first-of-type': {
                                                        backgroundColor: 'rgba(225, 6, 0, 0.08)',
                                                    }
                                                }}
                                            >
                                                <TableCell>
                                                    <Chip
                                                        label={result.position || '-'}
                                                        size="small"
                                                        sx={{
                                                            backgroundColor: index === 0
                                                                ? 'primary.main'
                                                                : result.position === 1
                                                                    ? 'rgba(225, 6, 0, 0.3)'
                                                                    : 'rgba(255, 255, 255, 0.08)',
                                                            color: index === 0 ? 'white' : 'text.primary',
                                                            fontWeight: 700,
                                                            minWidth: 36,
                                                        }}
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                                        {result.full_name}
                                                    </Typography>
                                                </TableCell>
                                                <TableCell>
                                                    {result.country_code ? (
                                                        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                                                            <Typography variant="body2" sx={{ fontSize: '1.2rem' }}>
                                                                {getCountryFlagEmoji(result.country_code)}
                                                            </Typography>
                                                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                                                {getCountryName(result.country_code)}
                                                            </Typography>
                                                        </Stack>
                                                    ) : (
                                                        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                                                            —
                                                        </Typography>
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                                                        {result.driver_number}
                                                    </Typography>
                                                </TableCell>
                                                {columnVisibility.laps && (
                                                    <TableCell>
                                                        {result.number_of_laps !== null ? result.number_of_laps : (
                                                            <Typography variant="body2" sx={{ color: 'text.secondary' }}>-</Typography>
                                                        )}
                                                    </TableCell>
                                                )}
                                                <TableCell>
                                                    <Typography
                                                        variant="body2"
                                                        sx={{
                                                            fontFamily: 'monospace',
                                                            color: result.position === 1 ? 'primary.main' : 'text.primary',
                                                            fontWeight: result.position === 1 ? 700 : 400,
                                                        }}
                                                    >
                                                        {formatDuration(result.duration)}
                                                    </Typography>
                                                </TableCell>
                                                {columnVisibility.gapToLeader && (
                                                    <TableCell>
                                                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                                                            {formatDuration(result.gap_to_leader)}
                                                        </Typography>
                                                    </TableCell>
                                                )}
                                                {columnVisibility.dnf && (
                                                    <TableCell>
                                                        {result.dnf ? (
                                                            <Chip label="DNF" size="small" color="error" />
                                                        ) : (
                                                            <Typography variant="body2" sx={{ color: 'text.secondary' }}>-</Typography>
                                                        )}
                                                    </TableCell>
                                                )}
                                                {columnVisibility.dns && (
                                                    <TableCell>
                                                        {result.dns ? (
                                                            <Chip label="DNS" size="small" color="warning" />
                                                        ) : (
                                                            <Typography variant="body2" sx={{ color: 'text.secondary' }}>-</Typography>
                                                        )}
                                                    </TableCell>
                                                )}
                                                {columnVisibility.dsq && (
                                                    <TableCell>
                                                        {result.dsq ? (
                                                            <Chip label="DSQ" size="small" color="error" />
                                                        ) : (
                                                            <Typography variant="body2" sx={{ color: 'text.secondary' }}>-</Typography>
                                                        )}
                                                    </TableCell>
                                                )}
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* Lap Duration Comparison Chart */}
            {sessionResults.length > 0 && (
                <Card elevation={0} sx={{ mt: 3 }}>
                    <CardContent>
                        <Stack direction="row" spacing={2} sx={{ alignItems: 'center', mb: 3 }}>
                            <ShowChartIcon sx={{ color: 'primary.main', fontSize: 28 }} />
                            <Box>
                                <Typography variant="h2" component="h2" sx={{ mb: 0.5 }}>
                                    Lap Duration Comparison
                                </Typography>
                                <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                                    Compare lap times across drivers
                                </Typography>
                            </Box>
                        </Stack>

                        {/* Driver Selection Checkboxes */}
                        <Box sx={{ mb: 3 }}>
                            <Typography variant="body2" sx={{ mb: 1.5, fontWeight: 600, color: 'text.secondary' }}>
                                Select Drivers to Compare
                            </Typography>
                            <Box
                                sx={{
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: 1.5,
                                    p: 2,
                                    border: '1px solid',
                                    borderColor: 'divider',
                                    borderRadius: 2,
                                    backgroundColor: 'rgba(255, 255, 255, 0.02)',
                                }}
                            >
                                {sessionResults.map((result) => (
                                    <FormControlLabel
                                        key={result.driver_number}
                                        control={
                                            <Checkbox
                                                checked={selectedDrivers.has(result.driver_number)}
                                                onChange={() => handleDriverSelection(result.driver_number)}
                                                sx={{
                                                    color: 'text.secondary',
                                                    '&.Mui-checked': {
                                                        color: 'primary.main',
                                                    },
                                                }}
                                            />
                                        }
                                        label={
                                            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                                                {result.country_code && (
                                                    <Typography variant="body2" sx={{ fontSize: '1rem' }}>
                                                        {getCountryFlagEmoji(result.country_code)}
                                                    </Typography>
                                                )}
                                                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                                                    #{result.driver_number} {result.full_name}
                                                </Typography>
                                            </Stack>
                                        }
                                    />
                                ))}
                            </Box>
                        </Box>

                        {/* Chart */}
                        {loadingLapData.size > 0 ? (
                            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
                                <CircularProgress size={48} />
                            </Box>
                        ) : selectedDrivers.size === 0 ? (
                            <Box
                                sx={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                    py: 8,
                                    border: '1px dashed',
                                    borderColor: 'divider',
                                    borderRadius: 2,
                                }}
                            >
                                <Typography variant="body1" sx={{ color: 'text.secondary' }}>
                                    Select drivers above to compare lap times
                                </Typography>
                            </Box>
                        ) : lapData.length === 0 ? (
                            <Box
                                sx={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                    py: 8,
                                    border: '1px dashed',
                                    borderColor: 'divider',
                                    borderRadius: 2,
                                }}
                            >
                                <Typography variant="body1" sx={{ color: 'text.secondary' }}>
                                    No lap data available for selected drivers
                                </Typography>
                            </Box>
                        ) : (
                            <LapComparisonChart
                                lapData={lapData}
                                selectedDrivers={Array.from(selectedDrivers)}
                                sessionResults={sessionResults}
                                stints={stints}
                                raceControlEvents={raceControlEvents}
                            />
                        )}
                    </CardContent>
                </Card>
            )}
        </Box>
    );
};

export default Dashboard;
