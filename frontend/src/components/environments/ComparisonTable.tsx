/**
 * Side-by-side subsystem comparison, grouped by system.
 *
 * A plain Table rather than DataGrid: two-sided cells under group headers is
 * not something DataGrid expresses well, and a raw DataGrid would also need
 * `disableColumnFilter` to avoid offering a column filter that contradicts the
 * page's own summary.
 */
import { Fragment } from 'react';
import {
  Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import type {
  DifferenceKind, HostShapeEntry, SubsystemComparison,
} from '../../types/environmentComparison';

// Exported: the page's summary strip labels the same kinds, and two copies
// would drift.
// eslint-disable-next-line react-refresh/only-export-components
export const KIND_LABEL: Record<DifferenceKind, string> = {
  presence: 'Presence',
  mocked: 'Mocked',
  version: 'Version',
  host_shape: 'Hosts',
};

/** Count, type and role — never host names, which differ between environments by design. */
// eslint-disable-next-line react-refresh/only-export-components
export function formatHostShape(shape: HostShapeEntry[]): string {
  if (shape.length === 0) return '—';
  return shape
    .map((e) => `${e.count} × ${e.component_type}${e.role ? ` (${e.role})` : ''}`)
    .join(', ');
}

interface Props {
  rows: SubsystemComparison[];
  leftName: string;
  rightName: string;
  reference: 'left' | 'right' | null;
}

function missingLabel(
  row: SubsystemComparison, leftName: string, rightName: string,
  reference: 'left' | 'right' | null
): string {
  const absentFrom = row.presence === 'left_only' ? rightName : leftName;
  if (reference === null) return `Not in ${absentFrom}`;
  const presentSide = row.presence === 'left_only' ? 'left' : 'right';
  return presentSide === reference ? 'Missing from reference' : 'Extra vs reference';
}

function Side({ side }: { side: SubsystemComparison['left'] }) {
  if (side === null) return <Typography variant="body2" color="text.secondary">—</Typography>;
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2">{side.version ?? 'No version recorded'}</Typography>
      <Typography variant="caption" color="text.secondary">
        {side.is_mocked ? 'Mocked' : 'Real'}
        {side.mock_notes ? ` — ${side.mock_notes}` : ''}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {formatHostShape(side.host_shape)}
      </Typography>
    </Stack>
  );
}

export default function ComparisonTable({ rows, leftName, rightName, reference }: Props) {
  const bySystem = new Map<string, SubsystemComparison[]>();
  rows.forEach((row) => {
    const list = bySystem.get(row.system_name) ?? [];
    list.push(row);
    bySystem.set(row.system_name, list);
  });

  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Subsystem</TableCell>
          <TableCell>{leftName}</TableCell>
          <TableCell>{rightName}</TableCell>
          <TableCell>Differences</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {[...bySystem.entries()].map(([systemName, systemRows]) => (
          // A keyed Fragment, not `<>`: the shorthand cannot take a key, and
          // React warns on every group without one.
          <Fragment key={systemName}>
            <TableRow>
              <TableCell colSpan={4} sx={{ bgcolor: 'action.hover' }}>
                <Typography variant="subtitle2">{systemName}</Typography>
              </TableCell>
            </TableRow>
            {systemRows.map((row) => (
              <TableRow key={row.subsystem_id}>
                <TableCell>{row.name}</TableCell>
                <TableCell><Side side={row.left} /></TableCell>
                <TableCell><Side side={row.right} /></TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                    {row.presence !== 'both' && (
                      <Chip size="small" color="warning"
                            label={missingLabel(row, leftName, rightName, reference)} />
                    )}
                    {row.differences
                      .filter((kind) => kind !== 'presence')
                      .map((kind) => (
                        <Chip key={kind} size="small" label={KIND_LABEL[kind]} />
                      ))}
                    {row.differences.length === 0 && (
                      <Typography variant="caption" color="text.secondary">Match</Typography>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}
