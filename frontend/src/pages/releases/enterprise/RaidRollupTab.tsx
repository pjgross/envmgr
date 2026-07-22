/** RaidRollupTab — enterprise-wide RAID aggregation across member releases. */
import { useEffect, useState } from 'react';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import { useDispatch, useSelector } from 'react-redux';
import type { AppDispatch, RootState } from '../../../store';
import { fetchRaidConfig } from '../../../store/raidSlice';
import { raidService } from '../../../services/raidService';
import type { RaidRollupResponse, RaidRag } from '../../../types/raid';
import { RAID_TYPE_LABELS } from '../../../types/raid';
import type { ReleaseResponse } from '../../../types/release';
import { RAID_TYPES, ragColor } from '../../../components/releases/raid/raidConstants';

interface Props {
  release: ReleaseResponse;
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Paper variant="outlined" sx={{ px: 2, py: 1, minWidth: 96, textAlign: 'center' }}>
      <Typography variant="h5" sx={{ color: color ?? 'text.primary' }}>{value}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Paper>
  );
}

export function RaidRollupTab({ release }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const config = useSelector((s: RootState) => s.raid.config);
  const [rollup, setRollup] = useState<RaidRollupResponse | null>(null);

  useEffect(() => {
    dispatch(fetchRaidConfig());
  }, [dispatch]);

  useEffect(() => {
    if (release?.id == null) return;
    raidService.rollup(release.id).then(setRollup).catch(() => setRollup(null));
  }, [release?.id]);

  if (!rollup) {
    return <Typography color="text.secondary">No RAID data for this enterprise release yet.</Typography>;
  }

  const rags: RaidRag[] = ['red', 'amber', 'green'];

  const cols: GridColDef[] = [
    { field: 'ref_code', headerName: 'Ref', width: 90 },
    { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
    { field: 'severity', headerName: 'Severity', width: 100 },
    {
      field: 'rag',
      headerName: 'RAG',
      width: 90,
      renderCell: (params) =>
        params.row.rag ? (
          <Chip
            label={String(params.row.rag).toUpperCase()}
            size="small"
            sx={{ bgcolor: ragColor(params.row.rag as RaidRag, config), color: '#fff' }}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">—</Typography>
        ),
    },
  ];

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {RAID_TYPES.map((t) => (
          <Stat key={t} label={RAID_TYPE_LABELS[t]} value={rollup.counts_by_type[t] ?? 0} />
        ))}
        <Stat label="Open issues" value={rollup.open_issues} />
        <Stat
          label="Overdue reviews"
          value={rollup.overdue_reviews}
          color={rollup.overdue_reviews > 0 ? 'error.main' : undefined}
        />
      </Stack>

      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="caption" color="text.secondary">Risk/Issue RAG:</Typography>
        {rags.map((rag) => (
          <Chip
            key={rag}
            size="small"
            label={`${rag.toUpperCase()} ${rollup.counts_by_rag[rag] ?? 0}`}
            sx={{ bgcolor: ragColor(rag, config), color: '#fff' }}
          />
        ))}
      </Stack>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Top risks by severity</Typography>
        <Paper>
          <DataGrid
            rows={rollup.top_risks.map((r, idx) => ({ id: `${r.release_id}-${r.ref_code}-${idx}`, ...r }))}
            columns={cols}
            autoHeight
            hideFooter={rollup.top_risks.length <= 100}
          />
        </Paper>
      </Box>
    </Stack>
  );
}
