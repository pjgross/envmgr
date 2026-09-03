import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Typography,
  Button,
  CircularProgress,
  Alert,
  Paper,
  TextField,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Stack,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { fetchTenantSettings, updateTenantSettings } from '../../store/tenantAdminSlice';
import type { RootState, AppDispatch } from '../../store';
import PageHeader from '../../components/layout/PageHeader';

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
      <PageHeader title="Tenant settings" />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {saved && <Alert severity="success" sx={{ mb: 2 }}>Settings saved</Alert>}

      {loading && !settings ? (
        <CircularProgress />
      ) : (
        <>
          <Paper sx={{ p: 3, mb: 2 }}>
            <Stack spacing={2} sx={{ maxWidth: 480 }}>
              <TextField
                label="Name"
                value={settings?.name ?? ''}
                InputProps={{ readOnly: true }}
                helperText="Set when the tenant was provisioned; a master admin can change it under Platform → Tenants."
              />
              <TextField label="Slug" value={settings?.slug ?? ''} InputProps={{ readOnly: true }} />
            </Stack>
          </Paper>

          <Accordion variant="outlined" disableGutters TransitionProps={{ unmountOnExit: true }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography>Advanced</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                A free-form JSON document downstream features may read. Nothing on this page changes billing, identity or routing.
              </Typography>
              {jsonError && <Alert severity="error" sx={{ mb: 2 }}>{jsonError}</Alert>}
              <TextField
                label="Custom settings (JSON)"
                multiline
                fullWidth
                minRows={10}
                value={settingsJson}
                onChange={(e) => setSettingsJson(e.target.value)}
                inputProps={{ style: { fontFamily: 'monospace', fontSize: '14px' } }}
              />
              <Box sx={{ mt: 2 }}>
                <Button variant="contained" onClick={handleSave} disabled={loading}>
                  Save settings
                </Button>
              </Box>
            </AccordionDetails>
          </Accordion>
        </>
      )}
    </Box>
  );
}
