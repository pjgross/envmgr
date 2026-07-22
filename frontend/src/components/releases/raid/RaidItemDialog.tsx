/**
 * RaidItemDialog — create/edit a RAID item with type-aware fields, plus
 * (edit mode) promote, scope-link and relation pickers.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddLinkIcon from '@mui/icons-material/AddLink';
import type { AppDispatch, RootState } from '../../../store';
import {
  createRaidItem,
  updateRaidItem,
  promoteRaidItem,
} from '../../../store/raidSlice';
import { fetchUsers } from '../../../store/tenantAdminSlice';
import { raidService } from '../../../services/raidService';
import { releaseService } from '../../../services/releaseService';
import { useSnackbar } from '../../../hooks/useSnackbar';
import type {
  RaidItemResponse,
  RaidItemType,
  RaidItemCreatePayload,
  RaidItemUpdatePayload,
  RaidLinksResponse,
  RaidRelation,
} from '../../../types/raid';
import { RAID_RELATION_LABELS } from '../../../types/raid';
import type { ReleaseChangeResponse } from '../../../types/releaseChange';
import {
  RAID_STATUSES,
  VALIDATION_STATUSES,
  RESPONSE_STRATEGIES,
  DEPENDENCY_DIRECTIONS,
  titleCase,
} from './raidConstants';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  item?: RaidItemResponse | null;
  defaultType: RaidItemType;
  onChanged?: () => void;
}

const RELATIONS: RaidRelation[] = ['relates_to', 'caused_by', 'duplicates', 'blocks'];

const toDateInput = (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : '');
const orNull = (s: string): string | null => (s ? s : null);

export default function RaidItemDialog({ open, onClose, releaseId, item, defaultType, onChanged }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const isEdit = !!item;
  const itemType: RaidItemType = item?.item_type ?? defaultType;

  const users = useSelector((s: RootState) => s.tenantAdmin.users);
  const allItems = useSelector((s: RootState) => s.raid.items);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [ownerId, setOwnerId] = useState<string>('');
  const [status, setStatus] = useState('');
  const [targetDate, setTargetDate] = useState('');
  const [reviewDate, setReviewDate] = useState('');
  // scoring
  const [probability, setProbability] = useState<string>('');
  const [impact, setImpact] = useState<string>('');
  // risk
  const [responseStrategy, setResponseStrategy] = useState('');
  const [mitigationPlan, setMitigationPlan] = useState('');
  const [contingencyPlan, setContingencyPlan] = useState('');
  // assumption
  const [validationStatus, setValidationStatus] = useState('');
  const [evidence, setEvidence] = useState('');
  // issue
  const [resolutionPlan, setResolutionPlan] = useState('');
  const [escalated, setEscalated] = useState(false);
  // dependency
  const [direction, setDirection] = useState('');
  const [counterparty, setCounterparty] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [atRisk, setAtRisk] = useState(false);

  const [submitting, setSubmitting] = useState(false);

  // Links (edit mode only)
  const [links, setLinks] = useState<RaidLinksResponse | null>(null);
  const [scopeChoices, setScopeChoices] = useState<ReleaseChangeResponse[]>([]);
  const [scopePick, setScopePick] = useState<ReleaseChangeResponse | null>(null);
  const [relationPick, setRelationPick] = useState<RaidItemResponse | null>(null);
  const [relationKind, setRelationKind] = useState<RaidRelation>('relates_to');

  useEffect(() => {
    if (!open) return;
    dispatch(fetchUsers());
    setTitle(item?.title ?? '');
    setDescription(item?.description ?? '');
    setOwnerId(item?.owner_id != null ? String(item.owner_id) : '');
    setStatus(item?.status ?? '');
    setTargetDate(toDateInput(item?.target_date));
    setReviewDate(toDateInput(item?.review_date));
    setProbability(item?.probability != null ? String(item.probability) : '');
    setImpact(item?.impact != null ? String(item.impact) : '');
    setResponseStrategy(item?.response_strategy ?? '');
    setMitigationPlan(item?.mitigation_plan ?? '');
    setContingencyPlan(item?.contingency_plan ?? '');
    setValidationStatus(item?.validation_status ?? '');
    setEvidence(item?.evidence ?? '');
    setResolutionPlan(item?.resolution_plan ?? '');
    setEscalated(item?.escalated ?? false);
    setDirection(item?.direction ?? '');
    setCounterparty(item?.counterparty ?? '');
    setDueDate(toDateInput(item?.due_date));
    setAtRisk(item?.at_risk ?? false);
    setScopePick(null);
    setRelationPick(null);
    setRelationKind('relates_to');
    // load links + scope choices for edit mode
    if (item) {
      raidService.getLinks(releaseId, item.id).then(setLinks).catch(() => setLinks(null));
      releaseService.listChanges(releaseId).then(setScopeChoices).catch(() => setScopeChoices([]));
    } else {
      setLinks(null);
      setScopeChoices([]);
    }
  }, [open, item, releaseId, dispatch]);

  const scored = itemType === 'risk' || itemType === 'issue';

  const buildPayload = (): RaidItemCreatePayload | RaidItemUpdatePayload => {
    const base: RaidItemUpdatePayload = {
      title,
      description: orNull(description),
      owner_id: ownerId ? Number(ownerId) : null,
      target_date: orNull(targetDate),
      review_date: orNull(reviewDate),
    };
    if (scored) {
      base.probability = probability ? Number(probability) : null;
      base.impact = impact ? Number(impact) : null;
    }
    if (itemType === 'risk') {
      base.response_strategy = orNull(responseStrategy);
      base.mitigation_plan = orNull(mitigationPlan);
      base.contingency_plan = orNull(contingencyPlan);
    }
    if (itemType === 'assumption') {
      base.evidence = orNull(evidence);
    }
    if (itemType === 'issue') {
      base.resolution_plan = orNull(resolutionPlan);
      base.escalated = escalated;
    }
    if (itemType === 'dependency') {
      base.direction = orNull(direction);
      base.counterparty = orNull(counterparty);
      base.due_date = orNull(dueDate);
      base.at_risk = atRisk;
    }
    return base;
  };

  const handleSave = async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    try {
      if (isEdit && item) {
        const payload = buildPayload() as RaidItemUpdatePayload;
        if (status && status !== item.status) payload.status = status;
        if (itemType === 'assumption' && validationStatus) payload.validation_status = validationStatus;
        await dispatch(updateRaidItem({ releaseId, itemId: item.id, data: payload })).unwrap();
        snackbar.success(`${item.ref_code} updated`);
      } else {
        const payload = { ...(buildPayload() as RaidItemCreatePayload), item_type: itemType };
        await dispatch(createRaidItem({ releaseId, data: payload })).unwrap();
        snackbar.success('RAID item created');
      }
      onChanged?.();
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save item');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePromote = async (targetType: 'risk' | 'issue') => {
    if (!item) return;
    try {
      await dispatch(promoteRaidItem({ releaseId, itemId: item.id, targetType })).unwrap();
      snackbar.success(`Promoted to ${titleCase(targetType)}`);
      onChanged?.();
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to promote');
    }
  };

  const reloadLinks = async () => {
    if (item) setLinks(await raidService.getLinks(releaseId, item.id));
  };

  const handleAddScopeLink = async () => {
    if (!item || !scopePick) return;
    try {
      const updated = await raidService.addScopeLink(releaseId, item.id, scopePick.id);
      setLinks(updated);
      setScopePick(null);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to link scope item');
    }
  };

  const handleRemoveScopeLink = async (changeId: number) => {
    if (!item) return;
    await raidService.removeScopeLink(releaseId, item.id, changeId);
    await reloadLinks();
  };

  const handleAddRelation = async () => {
    if (!item || !relationPick) return;
    try {
      const updated = await raidService.addRelation(releaseId, item.id, relationPick.id, relationKind);
      setLinks(updated);
      setRelationPick(null);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to add relation');
    }
  };

  const handleRemoveRelation = async (toItemId: number, relation: RaidRelation) => {
    if (!item) return;
    await raidService.removeRelation(releaseId, item.id, toItemId, relation);
    await reloadLinks();
  };

  const scopeLabel = (c: ReleaseChangeResponse) =>
    `${c.external_key ? c.external_key + ' — ' : ''}${c.title}`;
  const itemById = (id: number) => allItems.find((i) => i.id === id);
  const changeById = (id: number) => scopeChoices.find((c) => c.id === id);

  // Promotion targets available for this source type.
  const promoteTargets = useMemo<Array<'risk' | 'issue'>>(() => {
    if (!isEdit) return [];
    if (itemType === 'risk') return ['issue'];
    if (itemType === 'assumption') return ['risk', 'issue'];
    if (itemType === 'dependency') return ['risk', 'issue'];
    if (itemType === 'issue') return ['risk'];
    return [];
  }, [isEdit, itemType]);

  const relationCandidates = allItems.filter((i) => i.id !== item?.id);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        {isEdit ? `Edit ${item?.ref_code}` : `Add ${titleCase(itemType)}`}
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
            required
          />
          <TextField
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
          <Stack direction="row" spacing={2}>
            <TextField
              select
              label="Owner"
              value={ownerId}
              onChange={(e) => setOwnerId(e.target.value)}
              fullWidth
            >
              <MenuItem value="">Unassigned</MenuItem>
              {users.map((u) => (
                <MenuItem key={u.id} value={String(u.id)}>{u.username}</MenuItem>
              ))}
            </TextField>
            {isEdit && (
              <TextField
                select
                label="Status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                fullWidth
              >
                {RAID_STATUSES[itemType].map((s) => (
                  <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>
                ))}
              </TextField>
            )}
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Target date"
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Review date"
              type="date"
              value={reviewDate}
              onChange={(e) => setReviewDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>

          {/* Scoring — risk / issue */}
          {scored && (
            <Stack direction="row" spacing={2}>
              <TextField
                select
                label="Probability"
                value={probability}
                onChange={(e) => setProbability(e.target.value)}
                fullWidth
              >
                <MenuItem value="">—</MenuItem>
                {[1, 2, 3, 4, 5].map((n) => (
                  <MenuItem key={n} value={String(n)}>{n}</MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Impact"
                value={impact}
                onChange={(e) => setImpact(e.target.value)}
                fullWidth
              >
                <MenuItem value="">—</MenuItem>
                {[1, 2, 3, 4, 5].map((n) => (
                  <MenuItem key={n} value={String(n)}>{n}</MenuItem>
                ))}
              </TextField>
            </Stack>
          )}

          {/* Risk-specific */}
          {itemType === 'risk' && (
            <>
              <TextField
                select
                label="Response strategy"
                value={responseStrategy}
                onChange={(e) => setResponseStrategy(e.target.value)}
                fullWidth
              >
                <MenuItem value="">—</MenuItem>
                {RESPONSE_STRATEGIES.map((s) => (
                  <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>
                ))}
              </TextField>
              <TextField
                label="Mitigation plan"
                value={mitigationPlan}
                onChange={(e) => setMitigationPlan(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
              <TextField
                label="Contingency plan"
                value={contingencyPlan}
                onChange={(e) => setContingencyPlan(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
            </>
          )}

          {/* Assumption-specific */}
          {itemType === 'assumption' && (
            <>
              {isEdit && (
                <TextField
                  select
                  label="Validation status"
                  value={validationStatus}
                  onChange={(e) => setValidationStatus(e.target.value)}
                  fullWidth
                >
                  {VALIDATION_STATUSES.map((s) => (
                    <MenuItem key={s} value={s}>{titleCase(s)}</MenuItem>
                  ))}
                </TextField>
              )}
              <TextField
                label="Evidence"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
            </>
          )}

          {/* Issue-specific */}
          {itemType === 'issue' && (
            <>
              <TextField
                label="Resolution plan"
                value={resolutionPlan}
                onChange={(e) => setResolutionPlan(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
              <FormControlLabel
                control={<Switch checked={escalated} onChange={(e) => setEscalated(e.target.checked)} />}
                label="Escalated"
              />
            </>
          )}

          {/* Dependency-specific */}
          {itemType === 'dependency' && (
            <>
              <Stack direction="row" spacing={2}>
                <TextField
                  select
                  label="Direction"
                  value={direction}
                  onChange={(e) => setDirection(e.target.value)}
                  fullWidth
                >
                  <MenuItem value="">—</MenuItem>
                  {DEPENDENCY_DIRECTIONS.map((d) => (
                    <MenuItem key={d} value={d}>{titleCase(d)}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Due date"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  fullWidth
                />
              </Stack>
              <TextField
                label="Counterparty"
                value={counterparty}
                onChange={(e) => setCounterparty(e.target.value)}
                fullWidth
              />
              <FormControlLabel
                control={<Switch checked={atRisk} onChange={(e) => setAtRisk(e.target.checked)} />}
                label="At risk"
              />
            </>
          )}

          {/* Links — edit mode only */}
          {isEdit && (
            <>
              <Divider textAlign="left">
                <Typography variant="overline">Linked scope items</Typography>
              </Divider>
              <Stack spacing={1}>
                {(links?.scope_change_ids ?? []).map((cid) => (
                  <Stack key={cid} direction="row" alignItems="center" spacing={1}>
                    <Chip
                      label={changeById(cid) ? scopeLabel(changeById(cid)!) : 'Linked scope item'}
                      size="small"
                    />
                    <Tooltip title="Unlink">
                      <IconButton size="small" color="error" onClick={() => handleRemoveScopeLink(cid)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                ))}
                <Stack direction="row" spacing={1} alignItems="center">
                  <Autocomplete
                    size="small"
                    sx={{ flexGrow: 1 }}
                    options={scopeChoices.filter(
                      (c) => !(links?.scope_change_ids ?? []).includes(c.id),
                    )}
                    getOptionLabel={scopeLabel}
                    value={scopePick}
                    onChange={(_, v) => setScopePick(v)}
                    renderInput={(params) => <TextField {...params} label="Link a scope item" />}
                  />
                  <Button
                    size="small"
                    startIcon={<AddLinkIcon />}
                    disabled={!scopePick}
                    onClick={handleAddScopeLink}
                  >
                    Link
                  </Button>
                </Stack>
              </Stack>

              <Divider textAlign="left">
                <Typography variant="overline">Related items</Typography>
              </Divider>
              <Stack spacing={1}>
                {(links?.relations ?? []).map((r) => (
                  <Stack key={`${r.to_item_id}-${r.relation}`} direction="row" alignItems="center" spacing={1}>
                    <Chip
                      label={`${RAID_RELATION_LABELS[r.relation]} → ${itemById(r.to_item_id)?.ref_code ?? 'linked item'}`}
                      size="small"
                    />
                    <Tooltip title="Remove relation">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => handleRemoveRelation(r.to_item_id, r.relation)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                ))}
                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    select
                    size="small"
                    label="Relation"
                    value={relationKind}
                    onChange={(e) => setRelationKind(e.target.value as RaidRelation)}
                    sx={{ minWidth: 130 }}
                  >
                    {RELATIONS.map((r) => (
                      <MenuItem key={r} value={r}>{RAID_RELATION_LABELS[r]}</MenuItem>
                    ))}
                  </TextField>
                  <Autocomplete
                    size="small"
                    sx={{ flexGrow: 1 }}
                    options={relationCandidates}
                    getOptionLabel={(i) => `${i.ref_code} — ${i.title}`}
                    value={relationPick}
                    onChange={(_, v) => setRelationPick(v)}
                    renderInput={(params) => <TextField {...params} label="Related item" />}
                  />
                  <Button size="small" disabled={!relationPick} onClick={handleAddRelation}>
                    Add
                  </Button>
                </Stack>
              </Stack>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ flexWrap: 'wrap' }}>
        {promoteTargets.map((t) => (
          <Button key={t} color="secondary" onClick={() => handlePromote(t)}>
            Promote to {titleCase(t)}
          </Button>
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Button onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={submitting || !title.trim()}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
