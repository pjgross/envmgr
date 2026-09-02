import { Box, Tab, Tabs, Typography } from '@mui/material';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
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
import { entityConfigPage, entityTabPath, type EntityPanel } from './entityConfigTabs';

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
  }
}

/**
 * `/admin/:entity/:tab`. The tab is a route segment, so a drawer item can
 * point straight at "Naming policy" and a reload lands on the same tab.
 * Which tabs an entity has is `ENTITY_CONFIG_PAGES`' business, not this file's.
 */
export default function EntityConfig() {
  const { entity, tab } = useParams<{ entity: string; tab?: string }>();
  const navigate = useNavigate();
  const page = entityConfigPage(entity);
  if (!page) return <NotFound />;

  const current = page.tabs.find((t) => t.key === tab);
  if (!current) return <Navigate replace to={entityTabPath(page.entity, page.tabs[0].key)} />;

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
          onChange={(_, key: string) => navigate(entityTabPath(page.entity, key))}
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
