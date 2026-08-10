import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  FormControlLabel,
  FormHelperText,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Select,
  Switch,
  TextField,
  Typography,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchNamingPolicy,
  saveNamingPolicy,
  previewNamingPolicy,
} from '../../store/environmentNamingPolicySlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { EnvironmentNamingPolicyUpdate } from '../../types/environment';

// The vocabulary the backend accepts, minus the custom-field half which is
// tenant data. 'tier' is deliberately absent: environment.tier_id is already
// nullable=False, so requiring it would be a check that can never fail — a
// permanently-green row that reads as governance.
const FIXED_ATTRIBUTES: { value: string; label: string }[] = [
  { value: 'owner', label: 'Owner' },
  { value: 'expiry', label: 'Expiry date' },
  { value: 'operations_group', label: 'Operations group' },
];

export default function EnvironmentNamingPolicyPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { policy, preview, loading, error } = useSelector(
    (s: RootState) => s.environmentNamingPolicy
  );
  const envFields = useSelector((s: RootState) => s.customField.definitions.environment);

  const [isEnabled, setIsEnabled] = useState(false);
  const [pattern, setPattern] = useState('');
  const [example, setExample] = useState('');
  const [attributes, setAttributes] = useState<string[]>([]);
  const [graceDays, setGraceDays] = useState(14);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    dispatch(fetchNamingPolicy());
    dispatch(fetchDefinitions('environment'));
  }, [dispatch]);

  // Seeded from the policy in force whenever it arrives or is re-saved. The
  // form is the draft; the store holds what the server last confirmed.
  useEffect(() => {
    if (!policy) return;
    setIsEnabled(policy.is_enabled);
    setPattern(policy.name_pattern ?? '');
    setExample(policy.name_pattern_example ?? '');
    setAttributes(policy.required_attributes);
    setGraceDays(policy.grace_days);
  }, [policy]);

  const attributeOptions = useMemo(
    () => [
      ...FIXED_ATTRIBUTES,
      // Suffixed, never the bare label. A tenant custom field may be LABELLED
      // exactly like one of the fixed attributes — the dev estate has one keyed
      // `owner`, labelled "Owner" — and two options reading "Owner" are
      // indistinguishable in the list and identical once selected as chips.
      // Same collision class the grid columns solved by namespacing `cf_`,
      // showing up in a picker instead of a column id.
      ...(envFields ?? []).map((f) => ({
        value: `cf:${f.field_key}`,
        label: `${f.label} (custom field)`,
      })),
    ],
    [envFields]
  );

  const labelFor = (value: string) =>
    attributeOptions.find((o) => o.value === value)?.label ?? value;

  // An empty pattern is "no naming rule, attributes only" — null, not ''. The
  // column is nullable and null is what the backend reads as "no rule".
  const patternOrNull = () => (pattern.trim() ? pattern.trim() : null);

  const draft = (): EnvironmentNamingPolicyUpdate => ({
    is_enabled: isEnabled,
    name_pattern: patternOrNull(),
    name_pattern_example: example.trim() ? example.trim() : null,
    required_attributes: attributes,
    grace_days: graceDays,
  });

  const handlePreview = () => {
    setSaved(false);
    // The CURRENT form values, not the saved ones: the question a preview
    // answers is "what would this rule do", before it is in force.
    dispatch(
      previewNamingPolicy({
        name_pattern: patternOrNull(),
        required_attributes: attributes,
      })
    );
  };

  const handleSave = async () => {
    setSaved(false);
    const result = await dispatch(saveNamingPolicy(draft()));
    if (saveNamingPolicy.fulfilled.match(result)) setSaved(true);
    // On rejection the slice holds formatApiError's text — the server's
    // `detail`, which for a refused example names the pattern that rejected it.
    // Reading result.error.message here would render "Request failed with
    // status code 422" instead.
  };

  return (
    <Box sx={{ mb: 4 }}>
      <Typography variant="h6" gutterBottom>
        Naming &amp; Tagging Policy
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Declare what an environment&apos;s name must look like and which attributes it must
        carry. A <strong>changed</strong> name that does not match the pattern is refused;
        everything else here reports.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          Policy saved.
        </Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 720 }}>
        <FormControlLabel
          control={
            <Switch
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              inputProps={{ 'aria-label': 'Policy enabled' }}
            />
          }
          label="Policy enabled"
        />

        <TextField
          label="Name pattern"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          disabled={loading}
          helperText="A regular expression the whole name must match. Leave blank to check attributes only."
        />

        <TextField
          label="Example name"
          value={example}
          onChange={(e) => setExample(e.target.value)}
          disabled={loading}
          helperText="Shown to whoever a save refuses, so it must be a name the pattern accepts — a save is refused if its own pattern rejects it."
        />

        <FormControl>
          <InputLabel id="required-attributes-label">Required attributes</InputLabel>
          <Select
            labelId="required-attributes-label"
            multiple
            value={attributes}
            onChange={(e) =>
              setAttributes(
                typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value
              )
            }
            input={<OutlinedInput label="Required attributes" />}
            renderValue={(selected) => (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {selected.map((v) => (
                  <Chip key={v} size="small" label={labelFor(v)} />
                ))}
              </Box>
            )}
          >
            {attributeOptions.map((o) => (
              <MenuItem key={o.value} value={o.value}>
                {o.label}
              </MenuItem>
            ))}
          </Select>
          <FormHelperText>
            This affects reporting only. To refuse a save outright, mark the custom field
            required in Custom Fields.
          </FormHelperText>
        </FormControl>

        <TextField
          label="Grace period (days)"
          type="number"
          value={graceDays}
          onChange={(e) => setGraceDays(Number(e.target.value))}
          inputProps={{ min: 0 }}
          helperText="How long an environment may fail the policy before it reads as quarantined. Counted from whichever is later: the policy's effective date or the environment's creation."
        />

        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" onClick={handlePreview} disabled={loading}>
            Preview
          </Button>
          <Button variant="contained" onClick={handleSave} disabled={loading}>
            Save
          </Button>
        </Box>

        {preview && (
          <Alert severity="info">
            <Typography>
              {preview.in_gap} of {preview.total_environments} environments would be in gap
            </Typography>
            <Typography>
              {preview.quarantined_now === 0
                ? 'None quarantined yet — the grace period has not elapsed for any of them.'
                : `${preview.quarantined_now} would read as quarantined immediately.`}
            </Typography>
            {preview.sample_names.length > 0 && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                Showing the first {preview.sample_names.length} of {preview.in_gap}:{' '}
                {preview.sample_names.join(', ')}
              </Typography>
            )}
          </Alert>
        )}

        <Typography variant="body2" color="text.secondary">
          Existing environments are never frozen: a save that keeps a non-conforming name
          unchanged is accepted, and nothing quarantines until the grace period elapses.
          Quarantine is a label and a filter — a quarantined environment can still be booked,
          deployed to and reported on.
        </Typography>

        {/* Gated on is_enabled, not on `policy` being present: a tenant that has
            never saved one reads as a DISABLED DEFAULT with `effective_from` set
            to now (the endpoint answers that rather than 404ing), so an ungated
            caption announced "In force since <today>" for a policy that was not
            in force and had never been saved. */}
        {policy?.is_enabled && (
          <Typography variant="caption" color="text.secondary">
            In force since {new Date(policy.effective_from).toLocaleDateString()}. This date
            resets whenever the pattern or the attribute list changes, granting fresh grace.
          </Typography>
        )}
      </Box>
    </Box>
  );
}
