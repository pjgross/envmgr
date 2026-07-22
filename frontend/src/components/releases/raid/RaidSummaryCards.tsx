/** RaidSummaryCards — headline counts for a release's RAID log. */
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import type { RaidSummaryResponse, RaidRag } from '../../../types/raid';
import { RAID_TYPE_LABELS } from '../../../types/raid';
import { RAID_TYPES, ragColor } from './raidConstants';
import type { RaidConfig } from '../../../types/raid';

interface Props {
  summary: RaidSummaryResponse | null;
  config: RaidConfig | null;
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Paper variant="outlined" sx={{ px: 2, py: 1, minWidth: 96, textAlign: 'center' }}>
      <Typography variant="h5" sx={{ color: color ?? 'text.primary' }}>{value}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Paper>
  );
}

export default function RaidSummaryCards({ summary, config }: Props) {
  if (!summary) return null;
  const rags: RaidRag[] = ['red', 'amber', 'green'];

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {RAID_TYPES.map((t) => (
          <Stat key={t} label={RAID_TYPE_LABELS[t]} value={summary.counts_by_type[t] ?? 0} />
        ))}
        <Stat label="Open issues" value={summary.open_issues} />
        <Stat
          label="Overdue reviews"
          value={summary.overdue_reviews}
          color={summary.overdue_reviews > 0 ? 'error.main' : undefined}
        />
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 1 }} alignItems="center">
        <Typography variant="caption" color="text.secondary">Risk/Issue RAG:</Typography>
        {rags.map((rag) => (
          <Chip
            key={rag}
            size="small"
            label={`${rag.toUpperCase()} ${summary.counts_by_rag[rag] ?? 0}`}
            sx={{ bgcolor: ragColor(rag, config), color: '#fff' }}
          />
        ))}
      </Stack>
    </Box>
  );
}
