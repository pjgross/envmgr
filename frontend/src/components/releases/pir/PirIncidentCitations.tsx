/**
 * The incidents cited as evidence for a finding.
 *
 * Each is a link by NAME to the incident itself: the incident is its own record,
 * raised by the ITIL process or by monitoring, and this review neither owns it
 * nor fixes it. Removing a citation is a correction — it deletes the link and
 * nothing else.
 *
 * NOT a `<Chip onDelete>`, which is what this was until the browser pass. MUI
 * renders that delete affordance as a bare `<svg>` with no role, no tabindex and
 * no accessible name, so the only way to remove a citation was a mouse click on
 * an unlabelled icon. It also puts the chip's `title` on the ROOT element, which
 * made the link's accessible name the note ("root incident") instead of the
 * incident — and made that name vary depending on whether anyone had typed one.
 * The remove control is a real button now, named after what it removes, and the
 * note is rendered as text rather than hidden in a tooltip no touch or keyboard
 * user can reach.
 */
import { Box, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { Link as RouterLink } from 'react-router-dom';
import type { PirCitation } from '../../../types/pir';

interface Props {
  citations: PirCitation[];
  onRemove: (incidentId: number) => void;
}

export default function PirIncidentCitations({ citations, onRemove }: Props) {
  if (citations.length === 0) return null;
  return (
    <Box sx={{ mt: 1.5 }}>
      <Typography variant="caption" color="text.secondary">Evidence</Typography>
      <Stack spacing={0.5} sx={{ mt: 0.5 }}>
        {citations.map((c) => (
          <Stack key={c.incident_id} direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" component={RouterLink} to={`/incidents/${c.incident_id}`}
                        sx={{ color: 'primary.main' }}>
              {c.severity} · {c.incident_title}
            </Typography>
            {c.note && (
              <Typography variant="caption" color="text.secondary">— {c.note}</Typography>
            )}
            <Tooltip title="Remove evidence">
              <IconButton
                size="small"
                aria-label={`Remove evidence ${c.incident_title}`}
                onClick={() => onRemove(c.incident_id)}
              >
                <CloseIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}
