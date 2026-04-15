import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Chip, Divider, Tab, Tabs, Typography } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';
import type { EntityType } from '../../types/customField';

const ENTITY_LABELS: Record<string, string> = {
  system: 'Systems',
  subsystem: 'Subsystems',
  'component-types': 'Component Types',
  environment: 'Environments',
  booking: 'Bookings',
};

export default function EntityConfig() {
  const { entityType } = useParams<{ entityType: string }>();
  const [tab, setTab] = useState(0);

  if (!entityType || !ENTITY_LABELS[entityType]) {
    return <Typography>Unknown entity type.</Typography>;
  }

  if (entityType === 'component-types') {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>Component Types</Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          Define component types with custom field schemas for subsystems.
        </Typography>
        <ComponentTypesPanel />
      </Box>
    );
  }

  const et = entityType as EntityType;
  const isBooking = et === 'booking';

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>{ENTITY_LABELS[et]} Configuration</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure custom fields and other {ENTITY_LABELS[et].toLowerCase()} settings for your tenant.
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Custom Fields" />
          {isBooking ? (
            <Tab label="Lifecycle" />
          ) : (
            <Tab
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  Lifecycle <Chip label="Coming Soon" size="small" />
                </Box>
              }
              disabled
            />
          )}
        </Tabs>
      </Box>

      {tab === 0 && <CustomFieldDefinitionManager entityType={et} />}

      {tab === 1 && isBooking && (
        <Box>
          <BookingTypesPanel />
          <Divider sx={{ my: 3 }} />
          <LifecycleTemplatesPanel />
        </Box>
      )}
    </Box>
  );
}
