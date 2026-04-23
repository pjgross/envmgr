/**
 * TenantScopeChangeRules — admin page to configure which change_kinds count
 * toward scope change tracking, and to add new tenant-specific kinds.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import {
  fetchScopeChangeRules,
  upsertScopeChangeRules,
} from '../../store/scopeChangeRulesSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ScopeChangeKindRuleUpsertItem } from '../../types/scopeChangeRule';

// Must mirror the backend regex in schemas/scope_change_rule.py.
const KIND_RE = /^[a-z][a-z0-9_-]*$/;
const KIND_MAX = 20;

export default function TenantScopeChangeRules() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { rules, loading, error } = useSelector((s: RootState) => s.scopeChangeRules);

  const [localRules, setLocalRules] = useState<ScopeChangeKindRuleUpsertItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [newKind, setNewKind] = useState('');

  useEffect(() => {
    dispatch(fetchScopeChangeRules());
  }, [dispatch]);

  useEffect(() => {
    setLocalRules(
      rules.map((r) => ({ change_kind: r.change_kind, counts_as_scope_change: r.counts_as_scope_change }))
    );
  }, [rules]);

  const existingKinds = useMemo(
    () => new Set(localRules.map((r) => r.change_kind)),
    [localRules],
  );

  const normalisedNew = newKind.trim().toLowerCase();
  const newKindError = (() => {
    if (!normalisedNew) return null;
    if (normalisedNew.length > KIND_MAX) return `Max ${KIND_MAX} characters`;
    if (!KIND_RE.test(normalisedNew)) return 'Lowercase letters, digits, _ or - only';
    if (existingKinds.has(normalisedNew)) return 'Already exists';
    return null;
  })();
  const canAdd = Boolean(normalisedNew) && !newKindError;

  const handleAdd = () => {
    if (!canAdd) return;
    setLocalRules((prev) => [
      ...prev,
      { change_kind: normalisedNew, counts_as_scope_change: false },
    ]);
    setNewKind('');
  };

  const handleToggle = (kind: string) => {
    setLocalRules((prev) =>
      prev.map((r) =>
        r.change_kind === kind
          ? { ...r, counts_as_scope_change: !r.counts_as_scope_change }
          : r
      )
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await dispatch(upsertScopeChangeRules(localRules)).unwrap();
      snackbar.success('Scope change rules saved');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save rules');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Scope Change Rules
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure which change kinds count towards scope change tracking on releases.
        You can also add new tenant-specific kinds here — they become available in
        the scope-item dialog as soon as you save.
      </Typography>

      {loading && !rules.length ? (
        <CircularProgress size={24} />
      ) : error ? (
        <Typography color="error">{error}</Typography>
      ) : (
        <>
          <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
            <Typography variant="subtitle2" gutterBottom>
              Add a new change kind
            </Typography>
            <Stack direction="row" spacing={2} alignItems="flex-start">
              <TextField
                size="small"
                label="Kind"
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && canAdd) {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
                error={Boolean(newKindError)}
                helperText={newKindError ?? 'e.g. chore, epic — lowercase, up to 20 chars'}
                disabled={saving}
                sx={{ minWidth: 280 }}
              />
              <Button
                variant="outlined"
                onClick={handleAdd}
                disabled={!canAdd || saving}
                sx={{ mt: 0.5 }}
              >
                Add
              </Button>
            </Stack>
          </Paper>

          <TableContainer component={Paper} variant="outlined" sx={{ mb: 3 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Change Kind</TableCell>
                  <TableCell align="center">Counts as scope change</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {localRules.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={2}>
                      <Typography variant="body2" color="text.secondary">
                        No rules configured yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  localRules.map((rule) => (
                    <TableRow key={rule.change_kind}>
                      <TableCell>{rule.change_kind}</TableCell>
                      <TableCell align="center">
                        <Switch
                          checked={rule.counts_as_scope_change}
                          onChange={() => handleToggle(rule.change_kind)}
                          disabled={saving}
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <Button
            variant="contained"
            onClick={handleSave}
            disabled={saving || loading}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </>
      )}
    </Box>
  );
}
