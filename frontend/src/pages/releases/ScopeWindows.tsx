import { Box, Typography } from '@mui/material';
import ScopeWindowsTable from '../../components/releases/ScopeWindowsTable';

export default function ScopeWindows() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Scope Windows
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Find a system's releases and see which scope cutoffs are still open.
      </Typography>
      <ScopeWindowsTable showSystemFilter />
    </Box>
  );
}
