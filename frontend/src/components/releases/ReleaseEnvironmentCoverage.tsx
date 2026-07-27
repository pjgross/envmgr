/**
 * ReleaseEnvironmentCoverage — which environments host the systems this release
 * must test (Changing + Regression), with gaps and a suggested covering set.
 * Read-only insight; the Book button reuses the existing booking dialog.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Box, Button, Checkbox, Chip, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import { releaseService } from '../../services/releaseService';
import type { ReleaseEnvironmentCoverageResponse } from '../../types/release';
import {
  RELEASE_SYSTEM_ROLE_LABELS,
  RELEASE_SYSTEM_ROLE_COLORS,
  type ReleaseSystemRole,
} from '../../utils/releaseSystemRoles';

interface Props {
  releaseId: number;
  onBook: (environmentId: number) => void;
  onBookMany: (environmentIds: number[]) => void;
}

/** Greedy set-cover: fewest environments covering all coverable system ids. */
function greedyCover(
  environments: ReleaseEnvironmentCoverageResponse['environments'],
  coverable: Set<number>,
): ReleaseEnvironmentCoverageResponse['environments'] {
  const remaining = new Set(coverable);
  const chosen: ReleaseEnvironmentCoverageResponse['environments'] = [];
  while (remaining.size > 0) {
    let best: (typeof environments)[number] | null = null;
    let bestCount = 0;
    for (const e of environments) {
      const count = e.covered_system_ids.filter((id) => remaining.has(id)).length;
      if (count > bestCount) {
        bestCount = count;
        best = e;
      }
    }
    if (!best || bestCount === 0) break;
    chosen.push(best);
    best.covered_system_ids.forEach((id) => remaining.delete(id));
  }
  return chosen;
}

export default function ReleaseEnvironmentCoverage({ releaseId, onBook, onBookMany }: Props) {
  const [data, setData] = useState<ReleaseEnvironmentCoverageResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toggleEnv = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    releaseService.getEnvironmentCoverage(releaseId).then(setData).catch(() => setData(null));
  }, [releaseId]);

  const nameById = useMemo(() => {
    const m = new Map<number, string>();
    data?.needed_systems.forEach((s) => m.set(s.system_id, s.system_name));
    return m;
  }, [data]);

  const suggestion = useMemo(() => {
    if (!data) return [];
    const uncovered = new Set(data.uncovered_system_ids);
    const coverable = new Set(
      data.needed_systems.map((s) => s.system_id).filter((id) => !uncovered.has(id)),
    );
    return greedyCover(data.environments, coverable).map((e) => e.name);
  }, [data]);

  if (!data) return null;

  if (data.needed_systems.length === 0) {
    return (
      <Alert severity="info" variant="outlined">
        Add Changing or Regression systems on the Systems tab to plan test environments.
      </Alert>
    );
  }

  const uncoveredSet = new Set(data.uncovered_system_ids);

  return (
    <Box>
      <Typography variant="subtitle1" fontWeight="medium" sx={{ mb: 1 }}>
        Test Environment Coverage
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        <Button
          size="small"
          variant="contained"
          disabled={selected.size === 0}
          onClick={() => onBookMany(Array.from(selected))}
        >
          Book selected ({selected.size})
        </Button>
        {suggestion.length > 0 && (
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              const ids = data.environments
                .filter((e) => suggestion.includes(e.name))
                .map((e) => e.environment_id);
              setSelected(new Set(ids));
              onBookMany(ids);
            }}
          >
            Book suggested set
          </Button>
        )}
      </Box>

      {data.uncovered_system_ids.length > 0 && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {data.uncovered_system_ids.length} system(s) need testing but no environment hosts them:{' '}
          {data.uncovered_system_ids.map((id) => nameById.get(id) ?? `#${id}`).join(', ')}
        </Alert>
      )}

      {suggestion.length > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Suggested: booking <strong>{suggestion.join(' + ')}</strong> covers all testable systems.
        </Typography>
      )}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>System</TableCell>
            {data.environments.map((e) => (
              <TableCell key={e.environment_id} align="center">
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
                  <Checkbox
                    size="small"
                    checked={selected.has(e.environment_id)}
                    onChange={() => toggleEnv(e.environment_id)}
                    inputProps={{ 'aria-label': `Select ${e.name}` }}
                  />
                  <span>{e.name} ({e.covered_system_ids.length}/{data.needed_systems.length})</span>
                  <Button size="small" variant="outlined" onClick={() => onBook(e.environment_id)}>
                    Book
                  </Button>
                </Box>
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {data.needed_systems.map((s) => {
            const isGap = uncoveredSet.has(s.system_id);
            return (
              <TableRow key={s.system_id} sx={isGap ? { bgcolor: 'warning.light' } : undefined}>
                <TableCell>
                  {s.system_name}{' '}
                  <Chip
                    size="small"
                    label={RELEASE_SYSTEM_ROLE_LABELS[s.role as ReleaseSystemRole]}
                    color={RELEASE_SYSTEM_ROLE_COLORS[s.role as ReleaseSystemRole]}
                    sx={{ ml: 0.5 }}
                  />
                  {isGap && (
                    <Typography component="span" variant="caption" color="warning.dark" sx={{ ml: 1 }}>
                      no environment
                    </Typography>
                  )}
                </TableCell>
                {data.environments.map((e) => (
                  <TableCell key={e.environment_id} align="center">
                    {e.covered_system_ids.includes(s.system_id) ? (
                      <CheckIcon fontSize="small" color="success" />
                    ) : (
                      ''
                    )}
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
