import { Box } from '@mui/material';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';
import PageHeader from '../../components/layout/PageHeader';

/** `/admin/component-types` — the one entity-config page with no custom-field tab. */
export default function ComponentTypesPage() {
  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Component types"
        subtitle="Define component types with custom field schemas for subsystems."
      />
      <ComponentTypesPanel />
    </Box>
  );
}
