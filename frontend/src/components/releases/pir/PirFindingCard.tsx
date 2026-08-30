/**
 * One finding: what it was, why it happened, what is being done, what proves it.
 *
 * The root cause is shown only for a went-wrong finding — a "keep doing this"
 * item has no failure to analyse.
 */
import { useState } from 'react';
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
}

export default function PirFindingCard({
  finding, onEdit, onDelete, onAddAction, onEditAction, onDeleteAction, onRemoveCitation,
}: Props) {
  const [showActions] = useState(true);
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

        {showActions && (
          <PirActionsTable
            actions={finding.actions}
            onEdit={(a) => onEditAction(finding, a)}
            onDelete={(a) => onDeleteAction(finding, a)}
          />
        )}

        <PirIncidentCitations
          citations={finding.incidents}
          onRemove={(incidentId) => onRemoveCitation(finding, incidentId)}
        />

        <Button size="small" sx={{ mt: 1 }} onClick={() => onAddAction(finding)}>
          Add action
        </Button>
      </CardContent>
    </Card>
  );
}
