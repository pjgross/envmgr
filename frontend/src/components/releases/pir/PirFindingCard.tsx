/**
 * One finding: what it was, why it happened, what is being done, what proves it.
 *
 * The root cause is shown only for a went-wrong finding — a "keep doing this"
 * item has no failure to analyse.
 */
import {
  Box, Button, Card, CardContent, IconButton, Stack, Tooltip, Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import PirActionsTable from './PirActionsTable';
import PirIncidentCitations from './PirIncidentCitations';
import type { PirAction, PirFinding } from '../../../types/pir';

interface Props {
  finding: PirFinding;
  onEdit: (finding: PirFinding) => void;
  onDelete: (finding: PirFinding) => void;
  onAddAction: (finding: PirFinding) => void;
  onEditAction: (finding: PirFinding, action: PirAction) => void;
  onDeleteAction: (finding: PirFinding, action: PirAction) => void;
  onRemoveCitation: (finding: PirFinding, incidentId: number) => void;
  onCiteIncident: (finding: PirFinding) => void;
}

export default function PirFindingCard({
  finding, onEdit, onDelete, onAddAction, onEditAction, onDeleteAction, onRemoveCitation,
  onCiteIncident,
}: Props) {
  return (
    <Card variant="outlined" sx={{ mb: 2 }}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
          <Box sx={{ pr: 2 }}>
            <Typography variant="subtitle1" fontWeight={600}>{finding.title}</Typography>
            {finding.detail && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {finding.detail}
              </Typography>
            )}
          </Box>
          <Stack direction="row">
            <Tooltip title="Edit finding">
              <IconButton size="small" aria-label="Edit finding" onClick={() => onEdit(finding)}>
                <EditIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Delete finding">
              <IconButton size="small" aria-label="Delete finding"
                          onClick={() => onDelete(finding)}>
                <DeleteIcon fontSize="inherit" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Stack>

        {finding.kind === 'went_wrong' && finding.root_cause && (
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="caption" color="text.secondary">Root cause</Typography>
            <Typography variant="body2">{finding.root_cause}</Typography>
          </Box>
        )}

        <PirActionsTable
          actions={finding.actions}
          onEdit={(a) => onEditAction(finding, a)}
          onDelete={(a) => onDeleteAction(finding, a)}
        />

        <PirIncidentCitations
          citations={finding.incidents}
          onRemove={(incidentId) => onRemoveCitation(finding, incidentId)}
        />

        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <Button size="small" onClick={() => onAddAction(finding)}>
            Add action
          </Button>
          {/* An incident is evidence something went WRONG — offered only here,
              never on a went-well finding, matching the rule the server itself
              enforces on the composite incident-side endpoint. Rendered
              regardless of whether any citation already exists: with none yet,
              `PirIncidentCitations` renders nothing, and this is the only route
              back to citing one from the release side. */}
          {finding.kind === 'went_wrong' && (
            <Button size="small" onClick={() => onCiteIncident(finding)}>
              Cite an incident
            </Button>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
