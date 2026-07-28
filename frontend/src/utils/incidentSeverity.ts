import type { Severity } from '../types/incident';

export const SEVERITY_COLOR: Record<Severity, 'error' | 'warning' | 'info' | 'default'> = {
  P1: 'error',
  P2: 'warning',
  P3: 'info',
  P4: 'default',
};

export const SEVERITIES: Severity[] = ['P1', 'P2', 'P3', 'P4'];
