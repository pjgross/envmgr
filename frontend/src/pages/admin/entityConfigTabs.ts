import type { EntityType } from '../../types/customField';

/** URL segment for an admin entity page: `/admin/<entity>/<tab>`. */
export type AdminEntity =
  | 'environments'
  | 'environment-requests'
  | 'bookings'
  | 'releases'
  | 'release-changes'
  | 'change-requests'
  | 'builds'
  | 'deployments'
  | 'incidents'
  | 'systems'
  | 'subsystems';

export type EntityPanel =
  | 'fields'
  | 'lifecycle'
  | 'booking-types'
  | 'event-types'
  | 'gate-types'
  | 'rollback-policy'
  | 'tiers'
  | 'naming-policy'
  | 'lifecycle-policy';

export interface EntityConfigTab {
  key: string;
  label: string;
  panel: EntityPanel;
  /** One line describing what the tab configures — used by the /admin hub and
   *  by the drawer when a section is generated from an entity's full tab list. */
  description: string;
}

export interface EntityConfigPage {
  entity: AdminEntity;
  label: string;
  entityType: EntityType;
  tabs: EntityConfigTab[];
}

/**
 * The one table that says which entity has which configuration tab, in what
 * order, labelled how. The admin drawer's items, the /admin hub and the
 * EntityConfig page all derive from it — replacing the seven `*_SUPPORTED`
 * lists and the arithmetic tab indices EntityConfig used to compute from
 * them.
 *
 * Tabs are ordered most-specific-first, with the generic **Custom fields**
 * tab always last — `EntityConfig` redirects a bare `/admin/<entity>` to
 * `tabs[0]`, so this order also decides the landing tab.
 */
export const ENTITY_CONFIG_PAGES: EntityConfigPage[] = [
  {
    entity: 'environments',
    label: 'Environments',
    entityType: 'environment',
    tabs: [
      {
        key: 'tiers',
        label: 'Tiers',
        panel: 'tiers',
        description: 'The tier vocabulary (dev, SIT, UAT…) and per-tier idle thresholds.',
      },
      {
        key: 'naming-policy',
        label: 'Naming policy',
        panel: 'naming-policy',
        description: 'Name pattern, required attributes and quarantine grace.',
      },
      {
        key: 'lifecycle-policy',
        label: 'Decommissioning',
        panel: 'lifecycle-policy',
        description: 'Idle detection, notice period and the teardown checklist.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Tenant-defined fields on every environment.',
      },
    ],
  },
  {
    entity: 'environment-requests',
    label: 'Environment requests',
    entityType: 'environment_request',
    tabs: [
      {
        key: 'lifecycle',
        label: 'Lifecycle',
        panel: 'lifecycle',
        description: 'States and transitions for environment requests.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on environment requests.',
      },
    ],
  },
  {
    entity: 'bookings',
    label: 'Bookings',
    entityType: 'booking',
    tabs: [
      {
        key: 'types',
        label: 'Booking types',
        panel: 'booking-types',
        description: 'Types, default protection level and duration presets.',
      },
      {
        key: 'lifecycle',
        label: 'Lifecycle',
        panel: 'lifecycle',
        description: 'States and transitions for bookings.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Tenant-defined fields on every booking.',
      },
    ],
  },
  {
    entity: 'releases',
    label: 'Releases',
    entityType: 'release',
    tabs: [
      {
        key: 'gate-types',
        label: 'Gate types',
        panel: 'gate-types',
        description: 'The gate vocabulary, failure behaviour and expected evidence.',
      },
      {
        key: 'rollback-policy',
        label: 'Rollback policy',
        panel: 'rollback-policy',
        description: 'Whether a missing plan or stale rehearsal warns or blocks.',
      },
      {
        key: 'event-types',
        label: 'Event types',
        panel: 'event-types',
        description: 'Release calendar event types.',
      },
      {
        key: 'lifecycle',
        label: 'Lifecycle',
        panel: 'lifecycle',
        description: 'States and transitions for releases.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Tenant-defined fields on every release.',
      },
    ],
  },
  {
    entity: 'release-changes',
    label: 'Release scope items',
    entityType: 'release_change',
    tabs: [
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Tenant-defined fields on release scope items.',
      },
    ],
  },
  {
    entity: 'change-requests',
    label: 'Change requests',
    entityType: 'change_request',
    tabs: [
      {
        key: 'lifecycle',
        label: 'Lifecycle',
        panel: 'lifecycle',
        description: 'States and transitions for change requests.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Tenant-defined fields on every change request.',
      },
    ],
  },
  {
    entity: 'builds',
    label: 'Builds',
    entityType: 'build',
    tabs: [
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on builds.',
      },
    ],
  },
  {
    entity: 'deployments',
    label: 'Deployments',
    entityType: 'deployment',
    tabs: [
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on deployments.',
      },
    ],
  },
  {
    entity: 'incidents',
    label: 'Incidents',
    entityType: 'incident',
    tabs: [
      {
        key: 'lifecycle',
        label: 'Lifecycle',
        panel: 'lifecycle',
        description: 'States and transitions for incidents.',
      },
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on incidents.',
      },
    ],
  },
  {
    entity: 'systems',
    label: 'Systems',
    entityType: 'system',
    tabs: [
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on systems.',
      },
    ],
  },
  {
    entity: 'subsystems',
    label: 'Subsystems',
    entityType: 'subsystem',
    tabs: [
      {
        key: 'fields',
        label: 'Custom fields',
        panel: 'fields',
        description: 'Custom fields on subsystems.',
      },
    ],
  },
];

export function entityConfigPage(entity: string | undefined): EntityConfigPage | undefined {
  return ENTITY_CONFIG_PAGES.find((p) => p.entity === entity);
}

export function entityTabPath(entity: AdminEntity, tab: string): string {
  return `/admin/${entity}/${tab}`;
}
