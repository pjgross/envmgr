import { Box, Typography } from '@mui/material';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';

/** `/admin/component-types` — the one entity-config page with no custom-field tab. */
export default function ComponentTypesPage() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Component types
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Define component types with custom field schemas for subsystems.
      </Typography>
      <ComponentTypesPanel />
    </Box>
  );
}
