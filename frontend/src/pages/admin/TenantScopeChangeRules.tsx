/**
 * TenantScopeChangeRules — admin page to configure which change_kinds count
 * toward scope change tracking.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import {
  fetchScopeChangeRules,
  upsertScopeChangeRules,
} from '../../store/scopeChangeRulesSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ScopeChangeKindRuleUpsertItem } from '../../types/scopeChangeRule';

export default function TenantScopeChangeRules() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { rules, loading, error } = useSelector((s: RootState) => s.scopeChangeRules);

  // Local editable copy of toggle states
  const [localRules, setLocalRules] = useState<ScopeChangeKindRuleUpsertItem[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    dispatch(fetchScopeChangeRules());
  }, [dispatch]);

  useEffect(() => {
    setLocalRules(
      rules.map((r) => ({ change_kind: r.change_kind, counts_as_scope_change: r.counts_as_scope_change }))
    );
  }, [rules]);

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
      </Typography>

      {loading && !rules.length ? (
        <CircularProgress size={24} />
      ) : error ? (
        <Typography color="error">{error}</Typography>
      ) : (
        <>
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
