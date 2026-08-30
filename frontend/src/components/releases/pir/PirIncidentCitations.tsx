/**
 * The incidents cited as evidence for a finding.
 *
 * Each is a link by NAME to the incident itself: the incident is its own record,
 * raised by the ITIL process or by monitoring, and this review neither owns it
 * nor fixes it. Removing a citation is a correction — it deletes the link and
 * nothing else.
 */
import { Chip, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { PirCitation } from '../../../types/pir';

interface Props {
  citations: PirCitation[];
  onRemove: (incidentId: number) => void;
}

export default function PirIncidentCitations({ citations, onRemove }: Props) {
  if (citations.length === 0) return null;
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}
           alignItems="center">
      <Typography variant="body2" color="text.secondary">Evidence</Typography>
      {citations.map((c) => (
        <Chip
          key={c.incident_id}
          size="small"
          component={RouterLink}
          to={`/incidents/${c.incident_id}`}
          clickable
          label={`${c.severity} · ${c.incident_title}`}
          onDelete={() => onRemove(c.incident_id)}
          title={c.note ?? undefined}
        />
      ))}
    </Stack>
  );
}
