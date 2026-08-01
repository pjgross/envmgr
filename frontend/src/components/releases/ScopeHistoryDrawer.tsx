/**
 * ScopeHistoryDrawer — right-hand drawer showing combined move + status history
 * for a scope item (release change).
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import HistoryIcon from '@mui/icons-material/History';
import { AppDispatch, RootState } from '../../store';
import {
  fetchReleaseChangeReleaseHistory,
  fetchReleaseChangeStatusHistory,
} from '../../store/releaseSlice';
import { releaseService } from '../../services/releaseService';

interface Props {
  open: boolean;
  onClose: () => void;
  changeId: number;
  itemTitle?: string;
}

const DRAWER_WIDTH = 400;

type HistoryEntry =
  | { type: 'move'; at: Date; from_release_id: number | null; to_release_id: number | null; notes: string | null }
  | { type: 'status'; at: Date; from_status: string | null; to_status: string | null; notes: string | null };

export default function ScopeHistoryDrawer({ open, onClose, changeId, itemTitle }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  // NOT from state.release.list: that slice is ReleaseList's current filtered
  // page, so any release outside it would render as "Release #47". A picker
  // or lookup that wants every release has to ask for them itself. This is
  // the third component to need this — see MoveScopeItemDialog and
  // RequestAdmissionDialog for the same fix.
  const [releases, setReleases] = useState<{ id: number; name: string }[]>([]);
  const releaseHistory = useSelector((s: RootState) => s.release.changeReleaseHistory);
  const statusHistory = useSelector((s: RootState) => s.release.changeStatusHistory);
  const loading = useSelector((s: RootState) => s.release.loading);

  useEffect(() => {
    if (open) {
      dispatch(fetchReleaseChangeReleaseHistory(changeId));
      dispatch(fetchReleaseChangeStatusHistory(changeId));
    }
  }, [open, changeId, dispatch]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    releaseService
      .list({ limit: 200 })
      .then(({ rows }) => { if (!cancelled) setReleases(rows); })
      .catch(() => { if (!cancelled) setReleases([]); });
    return () => { cancelled = true; };
  }, [open]);

  const releaseNameById = useMemo(() => {
    const map: Record<number, string> = {};
    releases.forEach((r) => { map[r.id] = r.name; });
    return map;
  }, [releases]);

  const combined = useMemo<HistoryEntry[]>(() => {
    const moves: HistoryEntry[] = releaseHistory.map((h) => ({
      type: 'move',
      at: new Date(h.moved_at),
      from_release_id: h.from_release_id,
      to_release_id: h.to_release_id,
      notes: h.notes,
    }));
    const statuses: HistoryEntry[] = statusHistory.map((h) => ({
      type: 'status',
      at: new Date(h.changed_at),
      from_status: h.from_status,
      to_status: h.to_status,
      notes: h.notes,
    }));
    return [...moves, ...statuses].sort((a, b) => b.at.getTime() - a.at.getTime());
  }, [releaseHistory, statusHistory]);

  const releaseName = (id: number | null) =>
    id == null ? 'Backlog' : (releaseNameById[id] ?? `Release #${id}`);

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
            Scope Item History{itemTitle ? `: ${itemTitle}` : ''}
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
        ) : combined.length === 0 ? (
          <Typography color="text.secondary" variant="body2">
            No history yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {combined.map((entry, i) => (
              <ListItem key={i} disableGutters alignItems="flex-start" sx={{ py: 0.5 }}>
                <ListItemIcon sx={{ minWidth: 36, mt: 0.5 }}>
                  {entry.type === 'move' ? (
                    <CompareArrowsIcon fontSize="small" color="primary" />
                  ) : (
                    <HistoryIcon fontSize="small" color="action" />
                  )}
                </ListItemIcon>
                <ListItemText
                  primary={
                    entry.type === 'move' ? (
                      <Typography variant="body2">
                        Moved: {releaseName(entry.from_release_id)} → {releaseName(entry.to_release_id)}
                      </Typography>
                    ) : (
                      <Typography variant="body2">
                        Status:{' '}
                        {entry.from_status ? `${entry.from_status} → ` : ''}
                        {entry.to_status ?? '—'}
                      </Typography>
                    )
                  }
                  secondary={
                    <>
                      {entry.at.toLocaleString()}
                      {entry.notes ? ` — ${entry.notes}` : ''}
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
