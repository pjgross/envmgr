/**
 * EnvironmentOperatingHoursTab — weekly operating-hours editor + a utilization card.
 * Local-state + direct-service; mirrors the DoraDashboard/HealthDashboard pattern.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Autocomplete, Box, Button, Card, CardContent, Checkbox, FormControlLabel,
  Snackbar, TextField, Typography,
} from '@mui/material';
import { environmentOperatingHoursService } from '../../services/environmentOperatingHoursService';
import type { OperatingHoursDay } from '../../types/environmentOperatingHours';

const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const DEFAULT_WEEK: OperatingHoursDay[] = [
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: true, open: '09:00', close: '17:00' },
  { closed: true, open: '09:00', close: '17:00' },
];

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return Number.isInteger(h) ? `${h}h` : `${h.toFixed(1)}h`;
}

// IANA zones from the browser; fall back to a short list if unsupported.
function tzOptions(): string[] {
  const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
  try {
    return fn ? fn('timeZone') : ['UTC', 'Europe/London', 'America/New_York'];
  } catch {
    return ['UTC', 'Europe/London', 'America/New_York'];
  }
}

export default function EnvironmentOperatingHoursTab({ envId }: { envId: number }) {
  const [timezone, setTimezone] = useState('UTC');
  const [week, setWeek] = useState<OperatingHoursDay[]>(DEFAULT_WEEK);
  const [util, setUtil] = useState<{ ratio: number; booked: number; total: number; configured: boolean } | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const zones = useMemo(tzOptions, []);
  const loadedRef = useRef(false);

  // last-90-day window for the utilization card
  const params = useMemo(() => ({
    date_from: isoDate(new Date(Date.now() - 90 * 864e5)),
    date_to: isoDate(new Date()),
  }), []);

  useEffect(() => {
    environmentOperatingHoursService.getConfig(envId).then((cfg) => {
      if (cfg.configured && cfg.week && cfg.timezone) {
        setTimezone(cfg.timezone);
        setWeek(cfg.week.map((d) => ({ closed: d.closed, open: d.open ?? '09:00', close: d.close ?? '17:00' })));
      }
      loadedRef.current = true;
    }).catch(() => { loadedRef.current = true; });
  }, [envId]);

  const refreshUtil = () => {
    environmentOperatingHoursService.utilization(envId, params)
      .then((u) => setUtil({ ratio: u.utilization_ratio, booked: u.booked_operating_seconds, total: u.total_operating_seconds, configured: u.configured }))
      .catch(() => setUtil(null));
  };
  useEffect(refreshUtil, [envId, params]);

  const setDay = (i: number, patch: Partial<OperatingHoursDay>) => {
    setWeek((w) => w.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  };

  const handleSave = () => {
    setError(null);
    environmentOperatingHoursService.putConfig(envId, { timezone, week })
      .then(() => { setSaved(true); refreshUtil(); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to save operating hours'));
  };

  return (
    <Box sx={{ p: 1 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>Operating Hours</Typography>

      {util && (
        <Card variant="outlined" sx={{ mb: 3, maxWidth: 360 }}>
          <CardContent>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Utilization (last 90 days)
            </Typography>
            {util.configured ? (
              <>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  {Math.round(util.ratio * 100)}%
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {formatHours(util.booked)} booked / {formatHours(util.total)} operating
                </Typography>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">Not configured yet</Typography>
            )}
          </CardContent>
        </Card>
      )}

      <Autocomplete
        size="small"
        sx={{ maxWidth: 360, mb: 2 }}
        options={zones}
        value={timezone}
        onChange={(_, v) => v && setTimezone(v)}
        renderInput={(p) => <TextField {...p} label="Timezone" />}
      />

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, maxWidth: 520 }}>
        {week.map((day, i) => (
          <Box key={DAY_LABELS[i]} sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography sx={{ width: 100 }}>{DAY_LABELS[i]}</Typography>
            <FormControlLabel
              control={<Checkbox checked={day.closed} onChange={(e) => setDay(i, { closed: e.target.checked })} />}
              label="Closed"
            />
            <TextField
              type="time" size="small" label="Open" disabled={day.closed}
              value={day.open ?? '09:00'} onChange={(e) => setDay(i, { open: e.target.value })}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              type="time" size="small" label="Close" disabled={day.closed}
              value={day.close ?? '17:00'} onChange={(e) => setDay(i, { close: e.target.value })}
              InputLabelProps={{ shrink: true }}
            />
          </Box>
        ))}
      </Box>

      {error && <Alert severity="error" sx={{ mt: 2, maxWidth: 520 }}>{error}</Alert>}

      <Button variant="contained" sx={{ mt: 2 }} onClick={handleSave}>Save</Button>

      <Snackbar
        open={saved} autoHideDuration={3000} onClose={() => setSaved(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="success" onClose={() => setSaved(false)}>Operating hours saved</Alert>
      </Snackbar>
    </Box>
  );
}
