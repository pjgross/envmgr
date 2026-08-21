import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Divider, Tab, Tabs, Typography } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';
import ReleaseEventTypesPanel from '../../components/admin/ReleaseEventTypesPanel';
import EnvironmentTiersPanel from '../../components/admin/EnvironmentTiersPanel';
import EnvironmentNamingPolicyPanel from '../../components/admin/EnvironmentNamingPolicyPanel';
import EnvironmentLifecyclePanel from '../../components/admin/EnvironmentLifecyclePanel';
import GateTypesPanel from '../../components/admin/GateTypesPanel';
import RollbackPolicyPanel from '../../components/admin/RollbackPolicyPanel';
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

// Entities that have a release-gate type vocabulary (Phase 9 C2). Gates
// belong to releases, the same way event types do, so it sits next to that
// tab rather than needing its own top-level admin page.
const GATE_TYPES_SUPPORTED: EntityType[] = ['release'];

// Entities that have a rollback policy (Phase 9 C4). Rollback plans belong
// to releases, the same way gates and event types do, so this sits next to
// Gate Types rather than needing its own top-level admin page.
const ROLLBACK_POLICY_SUPPORTED: EntityType[] = ['release'];

// Entities that have a tier vocabulary.
const TIERS_SUPPORTED: EntityType[] = ['environment'];

// Entities that have a naming & tagging policy (B2). Its own tab rather than a
// section under "Tiers": a naming rule is not a tier vocabulary, and an admin
// looking for it would not think to open Tiers.
const NAMING_POLICY_SUPPORTED: EntityType[] = ['environment'];

// Entities that have a lifecycle policy — idle detection + decommission
// notice period + the checklist vocabulary (B5). Its own tab for the same
// reason naming policy got one: this isn't a tier vocabulary and isn't a
// naming rule either.
const LIFECYCLE_POLICY_SUPPORTED: EntityType[] = ['environment'];

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
  const hasGateTypes = GATE_TYPES_SUPPORTED.includes(et);
  const hasRollbackPolicy = ROLLBACK_POLICY_SUPPORTED.includes(et);
  const hasTiers = TIERS_SUPPORTED.includes(et);
  const hasNamingPolicy = NAMING_POLICY_SUPPORTED.includes(et);
  const hasLifecyclePolicy = LIFECYCLE_POLICY_SUPPORTED.includes(et);
  const gateTypesTabIndex = 1 + (hasLifecycle ? 1 : 0) + (hasEventTypes ? 1 : 0);
  const rollbackPolicyTabIndex = gateTypesTabIndex + (hasGateTypes ? 1 : 0);
  const tiersTabIndex = rollbackPolicyTabIndex + (hasRollbackPolicy ? 1 : 0);
  const namingPolicyTabIndex = tiersTabIndex + (hasTiers ? 1 : 0);
  const lifecyclePolicyTabIndex = namingPolicyTabIndex + (hasNamingPolicy ? 1 : 0);

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
          {hasGateTypes && <Tab label="Gate Types" />}
          {hasRollbackPolicy && <Tab label="Rollback Policy" />}
          {hasTiers && <Tab label="Tiers" />}
          {hasNamingPolicy && <Tab label="Naming Policy" />}
          {hasLifecyclePolicy && <Tab label="Lifecycle & Decommissioning" />}
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

      {hasGateTypes && tab === gateTypesTabIndex && <GateTypesPanel />}

      {hasRollbackPolicy && tab === rollbackPolicyTabIndex && <RollbackPolicyPanel />}

      {hasTiers && tab === tiersTabIndex && <EnvironmentTiersPanel />}

      {hasNamingPolicy && tab === namingPolicyTabIndex && <EnvironmentNamingPolicyPanel />}

      {hasLifecyclePolicy && tab === lifecyclePolicyTabIndex && <EnvironmentLifecyclePanel />}
    </Box>
  );
}
