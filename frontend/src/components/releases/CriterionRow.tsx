import { Box, Checkbox, Chip, IconButton, Stack, Typography } from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GateCriterion } from '../../types/gateCriterion';

interface Props {
  criterion: GateCriterion;
  onToggle: (criterion: GateCriterion) => void;
  onEdit: (criterion: GateCriterion) => void;
  onDelete: (criterion: GateCriterion) => void;
}

export default function CriterionRow({ criterion, onToggle, onEdit, onDelete }: Props) {
  const due = criterion.due_date ? new Date(criterion.due_date).toLocaleDateString() : null;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', py: 0.5, pl: 4, gap: 1 }}>
      <Checkbox
        size="small"
        checked={criterion.status === 'done'}
        onChange={() => onToggle(criterion)}
        inputProps={{ 'aria-label': `Complete ${criterion.title}` }}
      />
      <Typography
        variant="body2"
        sx={{
          flex: 1,
          textDecoration: criterion.status === 'done' ? 'line-through' : 'none',
        }}
      >
        {criterion.title}
      </Typography>
      {due && (
        <Chip
          size="small"
          label={due}
          color={criterion.is_overdue ? 'error' : 'default'}
          variant={criterion.is_overdue ? 'filled' : 'outlined'}
        />
      )}
      {criterion.assigned_to_username && (
        <Chip size="small" label={criterion.assigned_to_username} variant="outlined" />
      )}
      <Stack direction="row">
        <IconButton size="small" onClick={() => onEdit(criterion)} aria-label="edit">
          <EditIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" onClick={() => onDelete(criterion)} aria-label="delete">
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Stack>
    </Box>
  );
}
