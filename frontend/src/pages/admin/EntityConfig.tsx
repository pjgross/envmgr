import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Divider, Tab, Tabs, Typography } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';
import ReleaseEventTypesPanel from '../../components/admin/ReleaseEventTypesPanel';
import EnvironmentTiersPanel from '../../components/admin/EnvironmentTiersPanel';
import type { EntityType } from '../../types/customField';

const ENTITY_LABELS: Record<string, string> = {
  system: 'Systems',
  subsystem: 'Subsystems',
  'component-types': 'Component Types',
  environment: 'Environments',
  booking: 'Bookings',
  'change-request': 'Change Requests',
  release: 'Releases',
  'release-change': 'Release scope item',
  build: 'Builds',
  deployment: 'Deployments',
  incident: 'Incidents',
  'environment-request': 'Environment Requests',
};

// URL-style entity slug (dash) → internal EntityType (underscore) where they differ.
const ENTITY_SLUG_TO_TYPE: Record<string, EntityType> = {
  system: 'system',
  subsystem: 'subsystem',
  environment: 'environment',
  booking: 'booking',
  'change-request': 'change_request',
  release: 'release',
  'release-change': 'release_change',
  build: 'build',
  deployment: 'deployment',
  incident: 'incident',
  'environment-request': 'environment_request',
};

// Entities whose Lifecycle tab is fully supported.
// I5: environment_request was missing here — the spec's whole justification
// for reusing lifecycle templates rather than a fixed status enum is that a
// tenant edits the template in this admin UI, which was untrue as shipped.
// Safe to add now that C1(b) refuses a template that renames a required
// state at save time, rather than accepting it and degrading silently.
const LIFECYCLE_SUPPORTED: EntityType[] = [
  'booking', 'change_request', 'release', 'incident', 'environment_request',
];

// Entities that have event types config.
const EVENT_TYPES_SUPPORTED: EntityType[] = ['release'];

// Entities that have a tier vocabulary.
const TIERS_SUPPORTED: EntityType[] = ['environment'];

export default function EntityConfig() {
  const { entityType } = useParams<{ entityType: string }>();
  const [tab, setTab] = useState(0);

  if (!entityType || !ENTITY_LABELS[entityType]) {
    return <Typography>Unknown entity type.</Typography>;
  }

  if (entityType === 'component-types') {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          Component Types
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          Define component types with custom field schemas for subsystems.
        </Typography>
        <ComponentTypesPanel />
      </Box>
    );
  }

  const et = ENTITY_SLUG_TO_TYPE[entityType];
  const label = ENTITY_LABELS[entityType];
  const hasLifecycle = LIFECYCLE_SUPPORTED.includes(et);
  const hasEventTypes = EVENT_TYPES_SUPPORTED.includes(et);
  const hasTiers = TIERS_SUPPORTED.includes(et);
  const tiersTabIndex = 1 + (hasLifecycle ? 1 : 0) + (hasEventTypes ? 1 : 0);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {label} Configuration
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure custom fields and other {label.toLowerCase()} settings for your tenant.
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Custom Fields" />
          {hasLifecycle && <Tab label="Lifecycle" />}
          {hasEventTypes && <Tab label="Event Types" />}
          {hasTiers && <Tab label="Tiers" />}
        </Tabs>
      </Box>

      {tab === 0 && <CustomFieldDefinitionManager entityType={et} />}

      {tab === 1 && hasLifecycle && (
        <Box>
          {et === 'booking' && (
            <>
              <BookingTypesPanel />
              <Divider sx={{ my: 3 }} />
            </>
          )}
          <LifecycleTemplatesPanel entityType={et} />
        </Box>
      )}

      {hasEventTypes && tab === (hasLifecycle ? 2 : 1) && (
        <ReleaseEventTypesPanel />
      )}

      {hasTiers && tab === tiersTabIndex && <EnvironmentTiersPanel />}
    </Box>
  );
}
