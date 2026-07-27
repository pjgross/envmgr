export type ReleaseSystemRole = 'changing' | 'regression' | 'config_only';

export const RELEASE_SYSTEM_ROLE_LABELS: Record<ReleaseSystemRole, string> = {
  changing: 'Changing',
  regression: 'Regression (needs testing)',
  config_only: 'Config only',
};

export const RELEASE_SYSTEM_ROLE_COLORS: Record<
  ReleaseSystemRole,
  'primary' | 'warning' | 'default'
> = {
  changing: 'primary',
  regression: 'warning',
  config_only: 'default',
};

/** Fixed display/sort order for the three roles. */
export const RELEASE_SYSTEM_ROLE_ORDER: ReleaseSystemRole[] = [
  'changing',
  'regression',
  'config_only',
];
