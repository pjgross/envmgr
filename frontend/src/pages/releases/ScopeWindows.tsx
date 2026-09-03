import { Box } from '@mui/material';
import ScopeWindowsTable from '../../components/releases/ScopeWindowsTable';
import PageHeader from '../../components/layout/PageHeader';

export default function ScopeWindows() {
  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Scope Windows"
        subtitle="Find a system's releases and see which scope cutoffs are still open."
      />
      <ScopeWindowsTable showSystemFilter />
    </Box>
  );
}
