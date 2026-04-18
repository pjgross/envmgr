import { useCallback, useMemo, useState } from 'react';
import { Box, Typography } from '@mui/material';
import {
  DataGrid,
  GridColumnVisibilityModel,
  GridToolbar,
  type DataGridProps,
  type GridValidRowModel,
} from '@mui/x-data-grid';

type DataTableProps<R extends GridValidRowModel> = Omit<
  DataGridProps<R>,
  'columnVisibilityModel' | 'onColumnVisibilityModelChange' | 'slots' | 'slotProps'
> & {
  /** Stable key used to persist column visibility per user. Required. */
  storageKey: string;
  /** Optional scope (usually a user id) added to the localStorage key. */
  userId?: number | string;
  /** Text shown when rows is empty. */
  emptyMessage?: string;
  /** Set true to render the DataGrid toolbar (density toggle, columns, export, filters). */
  showToolbar?: boolean;
};

function loadVisibility(key: string): GridColumnVisibilityModel {
  try {
    const raw = localStorage.getItem(key);
    return raw ? ((JSON.parse(raw) as GridColumnVisibilityModel) ?? {}) : {};
  } catch {
    return {};
  }
}

function saveVisibility(key: string, model: GridColumnVisibilityModel): void {
  try {
    localStorage.setItem(key, JSON.stringify(model));
  } catch {
    // ignore storage failures (quota, privacy mode)
  }
}

function NoRowsOverlay({ message }: { message: string }) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        p: 3,
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Box>
  );
}

export default function DataTable<R extends GridValidRowModel>({
  storageKey,
  userId,
  emptyMessage = 'No rows to display',
  showToolbar = true,
  ...rest
}: DataTableProps<R>) {
  const fullKey = useMemo(
    () => (userId === undefined ? storageKey : `${storageKey}-${userId}`),
    [storageKey, userId]
  );

  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadVisibility(fullKey)
  );

  const handleVisibilityChange = useCallback(
    (next: GridColumnVisibilityModel) => {
      setColumnVisibilityModel(next);
      saveVisibility(fullKey, next);
    },
    [fullKey]
  );

  return (
    <DataGrid<R>
      density="standard"
      disableRowSelectionOnClick
      pageSizeOptions={[10, 25, 50, 100]}
      initialState={{
        pagination: { paginationModel: { pageSize: 25 } },
        ...rest.initialState,
      }}
      {...rest}
      columnVisibilityModel={columnVisibilityModel}
      onColumnVisibilityModelChange={handleVisibilityChange}
      slots={{
        ...(showToolbar ? { toolbar: GridToolbar } : {}),
        noRowsOverlay: () => <NoRowsOverlay message={emptyMessage} />,
      }}
      slotProps={{
        toolbar: { showQuickFilter: false },
      }}
    />
  );
}
