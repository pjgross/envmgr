import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Tab, Tabs, Typography, Chip } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import type { EntityType } from '../../types/customField';

const ENTITY_LABELS: Record<string, string> = {
  system: 'Systems',
  subsystem: 'Subsystems',
  environment: 'Environments',
  booking: 'Bookings',
};

export default function EntityConfig() {
  const { entityType } = useParams<{ entityType: string }>();
  const [tab, setTab] = useState(0);
  const et = entityType as EntityType;

  if (!ENTITY_LABELS[et]) {
    return <Typography>Unknown entity type.</Typography>;
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>{ENTITY_LABELS[et]} Configuration</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure custom fields and other {ENTITY_LABELS[et].toLowerCase()} settings for your tenant.
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Custom Fields" />
          <Tab label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>Lifecycle <Chip label="Coming Soon" size="small" /></Box>} disabled />
        </Tabs>
      </Box>

      {tab === 0 && <CustomFieldDefinitionManager entityType={et} />}
    </Box>
  );
}
