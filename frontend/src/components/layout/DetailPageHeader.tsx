import type { ReactNode } from 'react';
import { Box, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { Link as RouterLink } from 'react-router-dom';
import { usePageTitle } from '../../hooks/usePageTitle';

export interface DetailPageHeaderProps {
  /** An EXPLICIT target. Never history.back(): after a create, that is the form. */
  back: { to: string; label: string };
  title: string;
  status?: ReactNode;
  actions?: ReactNode;
}

export default function DetailPageHeader({ back, title, status, actions }: DetailPageHeaderProps) {
  // The entity's name is the one part of the title no static table can hold.
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
          <Typography component="h1" variant="h5" noWrap>
            {title}
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
