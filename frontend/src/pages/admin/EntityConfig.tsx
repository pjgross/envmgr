import { Box, Tab, Tabs, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import type { EntityType } from '../../types/customField';
import NotFound from '../../components/NotFound';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import EnvironmentLifecyclePanel from '../../components/admin/EnvironmentLifecyclePanel';
import EnvironmentNamingPolicyPanel from '../../components/admin/EnvironmentNamingPolicyPanel';
import EnvironmentTiersPanel from '../../components/admin/EnvironmentTiersPanel';
import GateTypesPanel from '../../components/admin/GateTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import ReleaseEventTypesPanel from '../../components/admin/ReleaseEventTypesPanel';
import RollbackPolicyPanel from '../../components/admin/RollbackPolicyPanel';
import { useUrlTab } from '../../hooks/useUrlTab';
import { entityConfigPage, type EntityPanel } from './entityConfigTabs';

function Panel({ panel, entityType }: { panel: EntityPanel; entityType: EntityType }) {
  switch (panel) {
    case 'fields':
      return <CustomFieldDefinitionManager entityType={entityType} />;
    case 'lifecycle':
      return <LifecycleTemplatesPanel entityType={entityType} />;
    case 'booking-types':
      return <BookingTypesPanel />;
    case 'event-types':
      return <ReleaseEventTypesPanel />;
    case 'gate-types':
      return <GateTypesPanel />;
    case 'rollback-policy':
      return <RollbackPolicyPanel />;
    case 'tiers':
      return <EnvironmentTiersPanel />;
    case 'naming-policy':
      return <EnvironmentNamingPolicyPanel />;
    case 'lifecycle-policy':
      return <EnvironmentLifecyclePanel />;
    default: {
      const _exhaustive: never = panel;
      return _exhaustive;
    }
  }
}

/**
 * `/admin/:entity?tab=<key>`. The tab is a query param (spec §6: one
 * mechanism app-wide), so a drawer item still points straight at "Naming
 * policy" via `entityTabPath`, and a reload or bookmark lands on the same
 * tab. Which tabs an entity has is `ENTITY_CONFIG_PAGES`' business, not this
 * file's. `useUrlTab` already falls back an unknown tab to the first one, so
 * this renders no redirect for that case — only an unknown entity is a 404.
 *
 * `useUrlTab` is called unconditionally, before the unknown-entity check:
 * React's rules of hooks forbid calling it only on the branch where `page`
 * resolves, so an absent page falls back to an empty tab vocabulary that is
 * never read — the 404 return happens right after.
 */
export default function EntityConfig() {
  const { entity } = useParams<{ entity: string }>();
  const page = entityConfigPage(entity);
  const [tab, setTab] = useUrlTab(
    page ? page.tabs.map((t) => t.key) : [],
    page ? page.tabs[0].key : '',
  );
  if (!page) return <NotFound />;

  const current = page.tabs.find((t) => t.key === tab) ?? page.tabs[0];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {page.label}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure {page.label.toLowerCase()} for your tenant.
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={current.key}
          onChange={(_, key: string) => setTab(key)}
          variant="scrollable"
          scrollButtons="auto"
        >
          {page.tabs.map((t) => (
            <Tab key={t.key} value={t.key} label={t.label} />
          ))}
        </Tabs>
      </Box>
      <Panel panel={current.panel} entityType={page.entityType} />
    </Box>
  );
}
