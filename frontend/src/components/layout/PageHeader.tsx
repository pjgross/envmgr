import type { ReactNode } from 'react';
import { Box, Breadcrumbs, Link, Skeleton, Stack, Typography } from '@mui/material';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { breadcrumbsFor } from './routeMeta';
import { usePageTitle } from '../../hooks/usePageTitle';

export interface PageHeaderProps {
  /**
   * Absent or empty while the page has nothing to show yet. Rendering an
   * empty `<h1>` is an accessibility defect (no accessible name), so the
   * component itself substitutes a skeleton rather than making every
   * consumer coalesce a possibly-null entity name to `''`.
   */
  title?: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

/**
 * The header every list and admin page composes through. The title is the
 * page's ONLY <h1> (audit P3-8), and breadcrumbs come from the route, not
 * from props — a page that could pass its own trail could disagree with the
 * drawer about where it sits.
 */
export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  const { pathname } = useLocation();
  const crumbs = breadcrumbsFor(pathname);
  usePageTitle();

  return (
    <Box sx={{ mb: 3 }}>
      {crumbs.length > 1 && (
        <Breadcrumbs sx={{ mb: 1 }}>
          {crumbs.map((c) =>
            c.to ? (
              <Link key={c.to} component={RouterLink} to={c.to} underline="hover" color="inherit">
                {c.label}
              </Link>
            ) : (
              <Typography key={c.label} color="text.primary">
                {c.label}
              </Typography>
            ),
          )}
        </Breadcrumbs>
      )}
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
        <Typography component="h1" variant="h5" aria-label={title ? undefined : 'Loading'}>
          {title ? title : <Skeleton variant="text" width={300} />}
        </Typography>
        {actions && (
          <Stack direction="row" spacing={1}>
            {actions}
          </Stack>
        )}
      </Stack>
      {subtitle && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {subtitle}
        </Typography>
      )}
    </Box>
  );
}
