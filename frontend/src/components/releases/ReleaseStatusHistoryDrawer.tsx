/**
 * ReleaseStatusHistoryDrawer — right-hand drawer showing status-change history
 * for a release. Reads GET /releases/:id/history via the release slice.
 */
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseHistory } from '../../store/releaseSlice';

interface Props {
  open: boolean;
  releaseId: number;
  onClose: () => void;
}

const DRAWER_WIDTH = 360;

export default function ReleaseStatusHistoryDrawer({ open, releaseId, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { history, loading } = useSelector((state: RootState) => state.release);

  useEffect(() => {
    if (open) {
      dispatch(fetchReleaseHistory(releaseId));
    }
  }, [open, releaseId, dispatch]);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}
    >
      <Toolbar />
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Status History
          </Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
        <Divider sx={{ mb: 2 }} />

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : history.length === 0 ? (
          <Typography color="text.secondary" variant="body2">
            No history yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {history.map((h) => (
              <ListItem key={h.id} disableGutters alignItems="flex-start" sx={{ py: 0.5 }}>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      {h.from_state ? (
                        <>
                          <Typography variant="body2" component="span">
                            {h.from_state}
                          </Typography>
                          <ArrowForwardIcon sx={{ fontSize: 14 }} />
                        </>
                      ) : null}
                      <Typography variant="body2" component="span" fontWeight="medium">
                        {h.to_state}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    <>
                      {new Date(h.changed_at).toLocaleString()}
                      {h.notes ? ` — ${h.notes}` : ''}
                    </>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </Box>
    </Drawer>
  );
}
