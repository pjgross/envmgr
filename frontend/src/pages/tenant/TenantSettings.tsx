import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Box, Typography, Button, CircularProgress, Alert, Paper, TextField } from '@mui/material';
import { fetchTenantSettings, updateTenantSettings } from '../../store/tenantAdminSlice';
import type { RootState, AppDispatch } from '../../store';

export default function TenantSettings() {
  const dispatch = useDispatch<AppDispatch>();
  const { settings, loading, error } = useSelector((state: RootState) => state.tenantAdmin);

  const [settingsJson, setSettingsJson] = useState('');
  const [jsonError, setJsonError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    dispatch(fetchTenantSettings());
  }, [dispatch]);

  useEffect(() => {
    if (settings?.settings !== undefined) {
      setSettingsJson(JSON.stringify(settings.settings ?? {}, null, 2));
    }
  }, [settings]);

  const handleSave = async () => {
    setJsonError('');
    setSaved(false);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(settingsJson);
    } catch {
      setJsonError('Invalid JSON');
      return;
    }
    try {
      await dispatch(updateTenantSettings(parsed)).unwrap();
      setSaved(true);
    } catch (err: unknown) {
      setJsonError(err instanceof Error ? err.message : 'Failed to save settings');
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Tenant Settings
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Settings saved successfully
        </Alert>
      )}

      {settings && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <Typography variant="body1">
            <strong>Name:</strong> {settings.name}
          </Typography>
          <Typography variant="body1">
            <strong>Slug:</strong> {settings.slug}
          </Typography>
        </Paper>
      )}

      {loading ? (
        <CircularProgress />
      ) : (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Custom Settings (JSON)
          </Typography>
          {jsonError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {jsonError}
            </Alert>
          )}
          <TextField
            multiline
            fullWidth
            minRows={10}
            value={settingsJson}
            onChange={(e) => setSettingsJson(e.target.value)}
            inputProps={{ style: { fontFamily: 'monospace', fontSize: '14px' } }}
          />
          <Box sx={{ mt: 2 }}>
            <Button variant="contained" onClick={handleSave} disabled={loading}>
              Save Settings
            </Button>
          </Box>
        </Paper>
      )}
    </Box>
  );
}
