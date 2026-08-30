/**
 * The process actions answering one finding.
 *
 * A plain Table rather than a DataGrid: this is a handful of rows inside a card,
 * and the tenant-wide worklist at /pir-actions is where paging, sorting and
 * filtering live.
 */
import {
  Chip, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import type { PirAction } from '../../../types/pir';

const STATUS_LABELS: Record<PirAction['status'], string> = {
  open: 'Open',
  in_progress: 'In progress',
  done: 'Done',
  cancelled: 'Cancelled',
};

const STATUS_COLOURS: Record<PirAction['status'], 'default' | 'info' | 'success'> = {
  open: 'default',
  in_progress: 'info',
  done: 'success',
  cancelled: 'default',
};

interface Props {
  actions: PirAction[];
  onEdit: (action: PirAction) => void;
  onDelete: (action: PirAction) => void;
}

function formatDue(due: string | null): string {
  if (!due) return '—';
  // UTC calendar day. The form writes a due date at T00:00:00Z, so rendering it
  // in local time shows the day before to anyone west of Greenwich.
  const d = new Date(due);
  return `${d.getUTCDate()} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })} ${d.getUTCFullYear()}`;
}

export default function PirActionsTable({ actions, onEdit, onDelete }: Props) {
  if (actions.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        No actions yet.
      </Typography>
    );
  }
  return (
    <Table size="small" sx={{ mt: 1 }}>
      <TableHead>
        <TableRow>
          <TableCell>Action</TableCell>
          <TableCell>Owner</TableCell>
          <TableCell>Due</TableCell>
          <TableCell>Status</TableCell>
          <TableCell align="right" />
        </TableRow>
      </TableHead>
      <TableBody>
        {actions.map((action) => (
          <TableRow key={action.id}>
            <TableCell>
              <Stack direction="row" spacing={1} alignItems="center">
                <span>{action.title}</span>
                {/* The server's verdict, never re-derived. `is_overdue` came from
                    one clock per request; comparing `due_date` here would let a
                    browser with a wrong clock manufacture a queue of overdue
                    rows nobody can clear. */}
                {action.is_overdue && <Chip size="small" color="error" label="Overdue" />}
              </Stack>
              {action.detail && (
                <Typography variant="caption" color="text.secondary" display="block">
                  {action.detail}
                </Typography>
              )}
            </TableCell>
            {/* The owner's NAME travels with the row. Never `#5`, and never
                resolved here against a separately-fetched, capped user list. */}
            <TableCell>{action.owner_username ?? '—'}</TableCell>
            <TableCell>{formatDue(action.due_date)}</TableCell>
            <TableCell>
              <Chip size="small" color={STATUS_COLOURS[action.status]}
                    label={STATUS_LABELS[action.status]} />
            </TableCell>
            <TableCell align="right">
              <Tooltip title="Edit action">
                <IconButton size="small" aria-label="Edit action" onClick={() => onEdit(action)}>
                  <EditIcon fontSize="inherit" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Delete action">
                <IconButton size="small" aria-label="Delete action"
                            onClick={() => onDelete(action)}>
                  <DeleteIcon fontSize="inherit" />
                </IconButton>
              </Tooltip>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
