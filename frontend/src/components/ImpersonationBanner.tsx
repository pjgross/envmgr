import { Alert, Button, Box } from '@mui/material';
import { useDispatch, useSelector } from 'react-redux';
import { exitImpersonation } from '../store/authSlice';
import type { RootState } from '../store';

export default function ImpersonationBanner() {
  const dispatch = useDispatch();
  const { impersonationMode, impersonatingTenant } = useSelector((state: RootState) => state.auth);

  if (!impersonationMode || !impersonatingTenant) return null;

  return (
    <Box sx={{ position: 'sticky', top: 0, zIndex: 1300 }}>
      <Alert
        severity="warning"
        action={
          <Button color="inherit" size="small" onClick={() => dispatch(exitImpersonation())}>
            Exit
          </Button>
        }
      >
        Viewing as <strong>{impersonatingTenant.name}</strong>. Exit to return to your account.
      </Alert>
    </Box>
  );
}
