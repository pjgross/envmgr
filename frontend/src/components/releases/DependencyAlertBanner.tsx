/**
 * DependencyAlertBanner — shows a warning when a dependency's target date has shifted
 * such that it may conflict with this release's schedule.
 */
import { useDispatch } from 'react-redux';
import { Alert, Box, Button, Typography } from '@mui/material';
import { AppDispatch } from '../../store';
import { acknowledgeAlert } from '../../store/releaseSlice';
import type { ReleaseDependencyAlert } from '../../types/release';

interface Props {
  releaseId: number;
  alerts: ReleaseDependencyAlert[];
}

export default function DependencyAlertBanner({ releaseId, alerts }: Props) {
  const dispatch = useDispatch<AppDispatch>();

  if (alerts.length === 0) return null;

  return (
    <Alert
      severity="warning"
      sx={{ mb: 2 }}
      action={
        alerts.length === 1 ? (
          <Button
            color="inherit"
            size="small"
            onClick={() =>
              dispatch(
                acknowledgeAlert({ releaseId, dependencyId: alerts[0].dependency_id })
              )
            }
          >
            Acknowledge
          </Button>
        ) : undefined
      }
    >
      <Typography variant="body2" fontWeight="medium">
        {alerts.length} dependency target date{alerts.length === 1 ? ' has' : 's have'} shifted
      </Typography>
      <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2 }}>
        {alerts.map((a) => (
          <li key={a.dependency_id}>
            <Typography variant="body2">
              <strong>{a.depends_on_name}</strong>: moved{' '}
              {a.diff_days > 0 ? `+${a.diff_days}` : a.diff_days} day
              {Math.abs(a.diff_days) !== 1 ? 's' : ''}.{' '}
              {alerts.length > 1 && (
                <Button
                  size="small"
                  variant="text"
                  sx={{ p: 0, minWidth: 0 }}
                  onClick={() =>
                    dispatch(
                      acknowledgeAlert({ releaseId, dependencyId: a.dependency_id })
                    )
                  }
                >
                  Dismiss
                </Button>
              )}
            </Typography>
          </li>
        ))}
      </Box>
    </Alert>
  );
}
