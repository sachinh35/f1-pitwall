import { useEffect, useState } from 'react';
import {
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions,
    TextField,
    Button,
    Typography,
    Box,
    CircularProgress,
    Alert,
} from '@mui/material';
import { updateF1TvToken } from '../services/api';

interface UpdateTokenDialogProps {
    open: boolean;
    onClose: () => void;
    onValidated: () => void;
    reason?: string | null;
}

const UpdateTokenDialog = ({ open, onClose, onValidated, reason }: UpdateTokenDialogProps) => {
    const [pastedToken, setPastedToken] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) return;
        // Resets the dialog's own form state each time it opens - this component stays
        // mounted (MUI's Dialog toggles visibility, not presence) across opens, so this is
        // the only point in its lifecycle where "opening" is observable at all.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setPastedToken('');
        setSubmitting(false);
        setError(null);
    }, [open]);

    const handleSubmit = () => {
        setSubmitting(true);
        setError(null);
        updateF1TvToken(pastedToken.trim())
            .then((status) => {
                if (status.valid) {
                    onValidated();
                } else {
                    setError(status.reason ?? 'Token is not valid.');
                }
            })
            .catch((err) => {
                console.error('Error updating F1TV token:', err);
                setError('Failed to validate the token. Please check your connection and try again.');
            })
            .finally(() => {
                setSubmitting(false);
            });
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>Update F1TV Token</DialogTitle>
            <DialogContent dividers>
                <Typography variant="body2" sx={{ mb: 2 }}>
                    {reason ?? 'Your F1TV token is missing or expired.'} A valid, non-expired F1TV subscription token
                    is required to capture car telemetry and position data during a live stream.
                </Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
                    To get a fresh token: log into{' '}
                    <Typography component="span" sx={{ fontWeight: 600 }}>
                        f1tv.formula1.com
                    </Typography>{' '}
                    in your browser, open DevTools → Network tab, find a request to{' '}
                    <Typography component="span" sx={{ fontWeight: 600 }}>
                        api.formula1.com
                    </Typography>
                    , and copy the value of its <code>Authorization: Bearer &lt;token&gt;</code> header (paste just
                    the token, without the "Bearer " prefix).
                </Typography>

                <TextField
                    label="F1TV JWT token"
                    placeholder="Paste the raw JWT token here"
                    value={pastedToken}
                    onChange={(e) => setPastedToken(e.target.value)}
                    multiline
                    minRows={4}
                    fullWidth
                    disabled={submitting}
                />

                {error && (
                    <Alert severity="error" sx={{ mt: 2 }}>
                        {error}
                    </Alert>
                )}

                {submitting && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 2 }}>
                        <CircularProgress size={20} />
                        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                            Validating token...
                        </Typography>
                    </Box>
                )}
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
                <Button onClick={onClose} disabled={submitting}>
                    Cancel
                </Button>
                <Button
                    variant="contained"
                    color="primary"
                    onClick={handleSubmit}
                    disabled={submitting || pastedToken.trim().length === 0}
                >
                    I've updated the token
                </Button>
            </DialogActions>
        </Dialog>
    );
};

export default UpdateTokenDialog;
export type { UpdateTokenDialogProps };
