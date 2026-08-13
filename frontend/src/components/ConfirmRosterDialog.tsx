import { useEffect, useState } from 'react';
import {
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions,
    Table,
    TableContainer,
    TableHead,
    TableBody,
    TableRow,
    TableCell,
    Select,
    MenuItem,
    TextField,
    Button,
    Typography,
    Box,
    CircularProgress,
    Alert,
    FormControl,
    Stack,
    SelectChangeEvent,
} from '@mui/material';
import {
    getTeamDriverPool,
    GetTeamDriverPoolResponse,
    TeamDriverPoolEntry,
    ConfirmedRosterEntry,
} from '../services/api';
import { TEAM_COLORS } from '../data/driverRoster';

interface ConfirmRosterDialogProps {
    open: boolean;
    onClose: () => void;
    onConfirm: (roster: ConfirmedRosterEntry[]) => void;
    title?: string;
}

const CUSTOM_OPTION = 'custom';

interface RowState {
    id: string;
    teamName: string;
    defaultDriverNumber: number;
    defaultTla: string;
    defaultFullName: string;
    editing: boolean;
    // '' (nothing picked yet), 'custom', or `reserve-{idx}` referring to that
    // team's reserves array.
    selection: string;
    driverNumberInput: string;
    tlaInput: string;
    fullNameInput: string;
}

const buildDefaultRows = (pool: GetTeamDriverPoolResponse): RowState[] => {
    const teamOrder: string[] = [];
    const seatsByTeam = new Map<string, TeamDriverPoolEntry[]>();

    pool.drivers.forEach((driver) => {
        if (driver.is_reserve) return;
        if (!seatsByTeam.has(driver.team_name)) {
            seatsByTeam.set(driver.team_name, []);
            teamOrder.push(driver.team_name);
        }
        seatsByTeam.get(driver.team_name)!.push(driver);
    });

    const rows: RowState[] = [];
    teamOrder.forEach((teamName) => {
        const seats = seatsByTeam.get(teamName) ?? [];
        seats.forEach((seat) => {
            rows.push({
                id: `${teamName}-${seat.driver_number}`,
                teamName,
                defaultDriverNumber: seat.driver_number as number,
                defaultTla: seat.tla ?? '',
                defaultFullName: seat.full_name,
                editing: false,
                selection: '',
                driverNumberInput: String(seat.driver_number ?? ''),
                tlaInput: seat.tla ?? '',
                fullNameInput: seat.full_name,
            });
        });
    });
    return rows;
};

const getReservesByTeam = (pool: GetTeamDriverPoolResponse | null): Record<string, TeamDriverPoolEntry[]> => {
    const map: Record<string, TeamDriverPoolEntry[]> = {};
    if (!pool) return map;
    pool.drivers.forEach((driver) => {
        if (!driver.is_reserve) return;
        if (!map[driver.team_name]) map[driver.team_name] = [];
        map[driver.team_name].push(driver);
    });
    return map;
};

const isPositiveInteger = (value: string): boolean => /^[1-9]\d*$/.test(value.trim());

const isRowValid = (row: RowState): boolean => {
    if (!row.editing) return true;
    if (!row.selection) return false;
    return (
        isPositiveInteger(row.driverNumberInput) &&
        row.tlaInput.trim().length > 0 &&
        row.fullNameInput.trim().length > 0
    );
};

const ConfirmRosterDialog = ({ open, onClose, onConfirm, title }: ConfirmRosterDialogProps) => {
    const [pool, setPool] = useState<GetTeamDriverPoolResponse | null>(null);
    const [rows, setRows] = useState<RowState[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const reservesByTeam = getReservesByTeam(pool);

    const fetchPool = () => {
        setLoading(true);
        setError(null);
        getTeamDriverPool(2026)
            .then((response) => {
                setPool(response);
                setRows(buildDefaultRows(response));
            })
            .catch((err) => {
                console.error('Error fetching team driver pool:', err);
                setError('Failed to load the driver lineup. Please check your connection and try again.');
            })
            .finally(() => {
                setLoading(false);
            });
    };

    useEffect(() => {
        if (!open) return;
        // Resets the dialog's own form state each time it opens - this component stays
        // mounted (MUI's Dialog toggles visibility, not presence) across opens, so this is
        // the only point in its lifecycle where "opening" is observable at all.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setPool(null);
        setRows([]);
        setError(null);
        fetchPool();
    }, [open]);

    const handleChangeClick = (rowId: string) => {
        setRows((prev) =>
            prev.map((row) => {
                if (row.id !== rowId) return row;
                const reserves = reservesByTeam[row.teamName] ?? [];
                if (reserves.length === 0) {
                    // Nothing to pick from - jump straight to a blank custom entry.
                    return {
                        ...row,
                        editing: true,
                        selection: CUSTOM_OPTION,
                        driverNumberInput: '',
                        tlaInput: '',
                        fullNameInput: '',
                    };
                }
                return { ...row, editing: true };
            })
        );
    };

    const handleResetClick = (rowId: string) => {
        setRows((prev) =>
            prev.map((row) =>
                row.id === rowId
                    ? {
                          ...row,
                          editing: false,
                          selection: '',
                          driverNumberInput: String(row.defaultDriverNumber),
                          tlaInput: row.defaultTla,
                          fullNameInput: row.defaultFullName,
                      }
                    : row
            )
        );
    };

    const handleSelectionChange = (rowId: string, value: string) => {
        setRows((prev) =>
            prev.map((row) => {
                if (row.id !== rowId) return row;
                if (value === CUSTOM_OPTION) {
                    return { ...row, selection: value, driverNumberInput: '', tlaInput: '', fullNameInput: '' };
                }
                const idx = parseInt(value.split('-')[1], 10);
                const reserve = (reservesByTeam[row.teamName] ?? [])[idx];
                if (!reserve) return row;
                return {
                    ...row,
                    selection: value,
                    driverNumberInput: reserve.driver_number != null ? String(reserve.driver_number) : '',
                    tlaInput: reserve.tla ?? '',
                    fullNameInput: reserve.full_name,
                };
            })
        );
    };

    const handleFieldChange = (rowId: string, field: 'driverNumberInput' | 'tlaInput' | 'fullNameInput', value: string) => {
        setRows((prev) => prev.map((row) => (row.id === rowId ? { ...row, [field]: value } : row)));
    };

    const allValid = rows.length > 0 && rows.every(isRowValid);

    const handleConfirmClick = () => {
        const roster: ConfirmedRosterEntry[] = rows.map((row) => ({
            driver_number: row.editing ? parseInt(row.driverNumberInput, 10) : row.defaultDriverNumber,
            tla: (row.editing ? row.tlaInput : row.defaultTla).trim(),
            full_name: (row.editing ? row.fullNameInput : row.defaultFullName).trim(),
            team_name: row.teamName,
            team_colour: TEAM_COLORS[row.teamName],
        }));
        onConfirm(roster);
    };

    // Which row id is the first (topmost) for its team, so we can span the team name cell
    // across that team's two seats - a plain pass over `rows` rather than mutating a variable
    // during the render-time .map() below (React may render more than once per commit, e.g.
    // StrictMode, so render-phase mutation of anything outside that single pass is unsafe).
    const firstRowIdByTeam = new Map<string, string>();
    for (const row of rows) {
        if (!firstRowIdByTeam.has(row.teamName)) firstRowIdByTeam.set(row.teamName, row.id);
    }

    return (
        <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
            <DialogTitle>{title ?? 'Confirm Driver Lineup'}</DialogTitle>
            <DialogContent dividers>
                {loading && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 6, gap: 2 }}>
                        <CircularProgress size={40} />
                        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                            Loading current lineup...
                        </Typography>
                    </Box>
                )}

                {!loading && error && (
                    <Box sx={{ py: 4 }}>
                        <Alert severity="error" sx={{ mb: 2 }}>
                            {error}
                        </Alert>
                        <Button variant="outlined" onClick={fetchPool}>
                            Retry
                        </Button>
                    </Box>
                )}

                {!loading && !error && rows.length > 0 && (
                    <>
                        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                            Review the drivers below. If a reserve or substitute driver is racing instead of the
                            usual seat-holder, click "Change" to swap them in.
                        </Typography>
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Team</TableCell>
                                        <TableCell>Driver #</TableCell>
                                        <TableCell>TLA</TableCell>
                                        <TableCell>Full Name</TableCell>
                                        <TableCell align="right">Actions</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {rows.map((row) => {
                                        const showTeamCell = firstRowIdByTeam.get(row.teamName) === row.id;
                                        const reserves = reservesByTeam[row.teamName] ?? [];
                                        const valid = isRowValid(row);

                                        return (
                                            <TableRow key={row.id} data-testid={`roster-row-${row.id}`}>
                                                {showTeamCell && (
                                                    <TableCell
                                                        rowSpan={
                                                            rows.filter((r) => r.teamName === row.teamName).length
                                                        }
                                                        sx={{ verticalAlign: 'top', fontWeight: 600 }}
                                                    >
                                                        {row.teamName}
                                                    </TableCell>
                                                )}

                                                {row.editing ? (
                                                    <>
                                                        <TableCell>
                                                            <TextField
                                                                size="small"
                                                                type="number"
                                                                value={row.driverNumberInput}
                                                                onChange={(e) =>
                                                                    handleFieldChange(row.id, 'driverNumberInput', e.target.value)
                                                                }
                                                                error={!isPositiveInteger(row.driverNumberInput)}
                                                                sx={{ width: 90 }}
                                                                slotProps={{ htmlInput: { 'aria-label': `${row.teamName} driver number` } }}
                                                            />
                                                        </TableCell>
                                                        <TableCell>
                                                            <TextField
                                                                size="small"
                                                                value={row.tlaInput}
                                                                onChange={(e) =>
                                                                    handleFieldChange(row.id, 'tlaInput', e.target.value.toUpperCase())
                                                                }
                                                                error={row.tlaInput.trim().length === 0}
                                                                sx={{ width: 90 }}
                                                                slotProps={{ htmlInput: { maxLength: 3, 'aria-label': `${row.teamName} TLA` } }}
                                                            />
                                                        </TableCell>
                                                        <TableCell>
                                                            <Stack spacing={1}>
                                                                <FormControl size="small" fullWidth>
                                                                    <Select
                                                                        displayEmpty
                                                                        value={row.selection}
                                                                        onChange={(e: SelectChangeEvent<string>) =>
                                                                            handleSelectionChange(row.id, e.target.value)
                                                                        }
                                                                        inputProps={{ 'aria-label': `${row.teamName} substitute driver` }}
                                                                    >
                                                                        <MenuItem value="" disabled>
                                                                            <em>Select substitute driver...</em>
                                                                        </MenuItem>
                                                                        {reserves.map((reserve, idx) => (
                                                                            <MenuItem key={`reserve-${idx}`} value={`reserve-${idx}`}>
                                                                                {reserve.full_name}
                                                                                {reserve.driver_number == null ? ' (no number on file)' : ''}
                                                                            </MenuItem>
                                                                        ))}
                                                                        <MenuItem value={CUSTOM_OPTION}>Custom...</MenuItem>
                                                                    </Select>
                                                                </FormControl>
                                                                {row.selection === CUSTOM_OPTION && (
                                                                    <TextField
                                                                        size="small"
                                                                        placeholder="Full name"
                                                                        value={row.fullNameInput}
                                                                        onChange={(e) =>
                                                                            handleFieldChange(row.id, 'fullNameInput', e.target.value)
                                                                        }
                                                                        error={row.fullNameInput.trim().length === 0}
                                                                        fullWidth
                                                                    />
                                                                )}
                                                            </Stack>
                                                        </TableCell>
                                                    </>
                                                ) : (
                                                    <>
                                                        <TableCell>{row.defaultDriverNumber}</TableCell>
                                                        <TableCell>{row.defaultTla}</TableCell>
                                                        <TableCell>{row.defaultFullName}</TableCell>
                                                    </>
                                                )}

                                                <TableCell align="right">
                                                    {row.editing ? (
                                                        <Button size="small" onClick={() => handleResetClick(row.id)}>
                                                            Reset to default
                                                        </Button>
                                                    ) : (
                                                        <Button size="small" onClick={() => handleChangeClick(row.id)}>
                                                            Change
                                                        </Button>
                                                    )}
                                                    {row.editing && !valid && (
                                                        <Typography
                                                            variant="caption"
                                                            sx={{ display: 'block', color: 'error.main', mt: 0.5 }}
                                                        >
                                                            Number and TLA required
                                                        </Typography>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </>
                )}
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={onClose}>Cancel</Button>
                <Button
                    variant="contained"
                    color="primary"
                    onClick={handleConfirmClick}
                    disabled={loading || !!error || !allValid}
                >
                    Confirm & Start
                </Button>
            </DialogActions>
        </Dialog>
    );
};

export default ConfirmRosterDialog;
export type { ConfirmRosterDialogProps };
