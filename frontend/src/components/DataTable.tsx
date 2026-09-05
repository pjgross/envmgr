import { useCallback, useEffect, useMemo, useState } from 'react';
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
  /**
   * Applied to the model read from localStorage, before it becomes state —
   * never to what is saved. A page whose columns are partly tenant-defined
   * uses this to drop entries naming a column that no longer exists, while
   * keeping namespaced custom-field keys whose definitions may not have
   * loaded yet. See EnvironmentList.
   */
  pruneStoredVisibility?: (stored: GridColumnVisibilityModel) => GridColumnVisibilityModel;
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
  pruneStoredVisibility,
  ...rest
}: DataTableProps<R>) {
  const fullKey = useMemo(
    () => (userId === undefined ? storageKey : `${storageKey}-${userId}`),
    [storageKey, userId]
  );

  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => {
      const stored = loadVisibility(fullKey);
      return pruneStoredVisibility ? pruneStoredVisibility(stored) : stored;
    }
  );

  // `fullKey` changes when `userId` resolves — a page whose user comes from an
  // async auth fetch mounts with it undefined. Reading storage only in the
  // initialiser above would drop that user's saved preference on the floor,
  // silently, on every such page. `pruneStoredVisibility` is deliberately not
  // in the dependency list: an inline arrow prop is a new identity every
  // render, which would re-read storage on every render and clobber an
  // in-session toggle.
  useEffect(() => {
    const stored = loadVisibility(fullKey);
    setColumnVisibilityModel(pruneStoredVisibility ? pruneStoredVisibility(stored) : stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullKey]);

  const handleVisibilityChange = useCallback(
    (next: GridColumnVisibilityModel) => {
      setColumnVisibilityModel(next);
      saveVisibility(fullKey, next);
    },
    [fullKey]
  );

  // MUI's DataGrid only reserves room for the noRows/noResults/loading overlay
  // when `autoHeight` is set: both the empty-content-height fallback in
  // useGridVirtualScroller and the overlay's own height fallback in
  // GridOverlays are gated on `rootProps.autoHeight`, so a grid that renders
  // zero rows without that prop collapses its virtual scroller (and the
  // overlay riding on top of it) to ~0px — the overlay's text is in the DOM
  // but its box has no height, so nobody sees it.
  //
  // DataTable does NOT default `autoHeight` on for that case, even though
  // roughly a third of its ~30 callers would benefit: about half of the rest
  // sit inside a wrapper with a genuine fixed height (600px, 520px, ...),
  // where the grid's real measured height is already non-zero with zero rows
  // and the overlay already renders correctly regardless of `autoHeight`. A
  // wrapper-level default that flipped `autoHeight` on whenever `rows` is
  // empty would ALSO apply MUI's autoHeight sizing to those grids the moment
  // they render with `rows === []` — which is every one of them, on every
  // page load, until the first fetch resolves — because
  // `GridRootStyles.js`'s `.MuiDataGrid-autoHeight { height: auto }` beats a
  // wrapper's fixed height. That shrinks a 600px grid to header-plus-two-
  // rows-of-empty-content and grows it back the moment real rows arrive, on
  // every load, for grids whose empty message was already visible. (This was
  // tried, and reverted — see the "empty-state overlay" describe block in
  // dataTableServerMode.test.tsx.)
  //
  // Instead, the handful of pages with NO bounded ancestor height at all
  // (BookingList, EnvironmentList, SystemCatalog, EnvironmentRequestList,
  // PirActionList, DecommissionWorklist, EscalationWorklist,
  // InfrastructureComponentList) pass `autoHeight` themselves,
  // unconditionally. That's safe specifically because those pages give the
  // grid no explicit height of its own (no fixed-height wrapper, no
  // definite-height ancestor for `height: 100%` to resolve against), so a
  // POPULATED grid there already sizes itself to its content exactly the way
  // `autoHeight` does — confirmed empirically (root height 249.75px /
  // scroller 104px, unchanged with `autoHeight` on or off). Any caller may
  // still pass `autoHeight` explicitly (in `rest`, spread below); DataTable
  // itself supplies no default either way.

  // `pagination: true` is a forced prop on the MIT DataGrid — `hideFooter`
  // only hides the pager UI, it does not turn paging off. So a client-mode
  // caller that hides the footer to render every row (the enterprise rollup
  // tabs: MembersTab's three grids, SystemsRollupTab) still gets paged by
  // this component's own `pageSize: 25` default, with no footer control left
  // to reach the rows past the first page — a `hideFooter` caller is
  // signalling it wants every row rendered, not a hidden 25-row window, so
  // skip the client-mode default for it exactly like server mode already
  // does (whose own pager MUI, not this footer, actually drives) and fall
  // back to MUI's un-paged-looking default of 100. A caller may still pass
  // its own smaller `initialState` if 100 is still too few.
  return (
    <DataGrid<R>
      density="standard"
      disableRowSelectionOnClick
      pageSizeOptions={[10, 25, 50, 100]}
      initialState={
        rest.paginationMode === 'server' || rest.hideFooter
          ? rest.initialState
          : {
              pagination: { paginationModel: { pageSize: 25 } },
              ...rest.initialState,
            }
      }
      // A server-mode grid's rows are one windowed page of a much larger
      // result set. `filterMode` defaults to `'client'` and the toolbar's
      // Filters panel isn't disabled by default, so a column filter would
      // silently filter only the page in hand while the footer keeps
      // showing the true server-side `rowCount` — the grid would lie about
      // what it's showing. Default filtering off for server mode unless the
      // caller explicitly opted back in; client-mode callers are untouched.
      disableColumnFilter={rest.paginationMode === 'server' ? true : undefined}
      {...rest}
      columnVisibilityModel={columnVisibilityModel}
      onColumnVisibilityModelChange={handleVisibilityChange}
      slots={{
        ...(showToolbar ? { toolbar: GridToolbar } : {}),
        noRowsOverlay: () => <NoRowsOverlay message={emptyMessage} />,
      }}
      slotProps={{
        toolbar: {
          showQuickFilter: false,
          // Same "the grid lies about what it's showing" hazard as the
          // Filters panel above, but for export: `GridToolbarExport`'s
          // csv/print export is wired independently of
          // `disableColumnFilter` and exports whatever rows are currently
          // loaded in the grid — one windowed page — while the footer
          // advertises the full server-side total. Suppress both export
          // buttons in server mode; client-mode callers already hold their
          // whole result set in `rows`, so export there is correct as-is.
          ...(rest.paginationMode === 'server'
            ? {
                csvOptions: { disableToolbarButton: true },
                printOptions: { disableToolbarButton: true },
              }
            : {}),
        },
      }}
    />
  );
}
