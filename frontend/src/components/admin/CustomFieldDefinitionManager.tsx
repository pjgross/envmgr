import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

import type { AppDispatch, RootState } from '../../store';
import { fetchDefinitions, deleteDefinition } from '../../store/customFieldSlice';
import CustomFieldDefinitionDialog from './CustomFieldDefinitionDialog';
import type { CustomFieldDefinition, EntityType } from '../../types/customField';
import { useConfirm } from '../../hooks/useConfirm';

const TYPE_COLORS: Record<string, 'primary' | 'warning' | 'success'> = {
  text: 'primary',
  number: 'warning',
  boolean: 'success',
};

interface Props {
  entityType: EntityType;
}

export default function CustomFieldDefinitionManager({ entityType }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { definitions, loading, error } = useSelector((state: RootState) => state.customField);
  const defs = definitions[entityType] ?? [];

  const { confirm, dialog: confirmDialog } = useConfirm();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<CustomFieldDefinition | null>(null);

  useEffect(() => {
    dispatch(fetchDefinitions(entityType));
  }, [dispatch, entityType]);

  const openCreate = () => {
    setEditTarget(null);
    setDialogOpen(true);
  };
  const openEdit = (d: CustomFieldDefinition) => {
    setEditTarget(d);
    setDialogOpen(true);
  };
  const handleDelete = async (id: number) => {
    if (!(await confirm({ message: 'Delete this field? This cannot be undone.', destructive: true }))) return;
    dispatch(deleteDefinition(id));
  };

  if (loading && defs.length === 0) return <Skeleton variant="rectangular" height={120} />;

  return (
    <Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {defs.length} field{defs.length !== 1 ? 's' : ''} defined
        </Typography>
        <Button startIcon={<AddIcon />} variant="contained" size="small" onClick={openCreate}>
          Add Field
        </Button>
      </Box>

      {defs.length === 0 ? (
        <Typography color="text.secondary" variant="body2">
          No custom fields yet.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Label</TableCell>
                <TableCell>Key</TableCell>
                <TableCell>Type</TableCell>
                {(entityType === 'release' || entityType === 'release_change') && <TableCell>Scope</TableCell>}
                <TableCell>Required</TableCell>
                <TableCell>Order</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {defs.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>{d.label}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {d.field_key}
                  </TableCell>
                  <TableCell>
                    <Chip label={d.field_type} color={TYPE_COLORS[d.field_type]} size="small" />
                  </TableCell>
                  {(entityType === 'release' || entityType === 'release_change') && (
                    <TableCell>
                      {d.entity_subtype ? (
                        <Chip label={d.entity_subtype} size="small" variant="outlined" />
                      ) : (
                        <Typography variant="caption" color="text.secondary">
                          All types
                        </Typography>
                      )}
                    </TableCell>
                  )}
                  <TableCell>{d.required ? '● Yes' : '○ No'}</TableCell>
                  <TableCell>{d.display_order}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => openEdit(d)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" onClick={() => handleDelete(d.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {confirmDialog}
      <CustomFieldDefinitionDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        entityType={entityType}
        editTarget={editTarget}
      />
    </Box>
  );
}
