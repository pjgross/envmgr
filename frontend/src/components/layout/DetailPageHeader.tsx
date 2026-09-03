import type { ReactNode } from 'react';
import { Box, IconButton, Skeleton, Stack, Tooltip, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { Link as RouterLink } from 'react-router-dom';
import { usePageTitle } from '../../hooks/usePageTitle';

export interface DetailPageHeaderProps {
  /** An EXPLICIT target. Never history.back(): after a create, that is the form. */
  back: { to: string; label: string };
  /**
   * Absent or empty while the entity is still loading — every detail page's
   * entity is typed `T | null` and its loading guard leaves a window where
   * the page renders on with a null entity. Rendering an empty `<h1>` is an
   * accessibility defect (no accessible name), so the component substitutes
   * a skeleton rather than making every consumer coalesce to `''`.
   */
  title?: string;
  status?: ReactNode;
  actions?: ReactNode;
}

export default function DetailPageHeader({ back, title, status, actions }: DetailPageHeaderProps) {
  // The entity's name is the one part of the title no static table can hold.
  // usePageTitle treats a falsy override (undefined or '') as "no override"
  // and falls back to the generic route trail — no leading " · ".
  usePageTitle(title);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ minWidth: 0 }}>
          <Tooltip title={`Back to ${back.label}`}>
            <IconButton component={RouterLink} to={back.to} aria-label={`Back to ${back.label}`} size="small">
              <ArrowBackIcon />
            </IconButton>
          </Tooltip>
          <Typography component="h1" variant="h5" noWrap aria-label={title ? undefined : 'Loading'}>
            {title ? title : <Skeleton variant="text" width={300} />}
          </Typography>
          {status}
        </Stack>
        {actions && (
          <Stack direction="row" spacing={1}>
            {actions}
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
