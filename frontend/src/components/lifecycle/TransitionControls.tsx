/**
 * TransitionControls
 *
 * Renders available lifecycle transition buttons for any lifecycle-managed
 * entity. Client-side pre-flight re-implements the Python validate_transition
 * logic so transitions that would fail on the server (missing required fields,
 * wrong role) are disabled with an explanatory tooltip before the request fires.
 *
 * When a valid transition is clicked, a small notes dialog opens; on confirm
 * `onTransition(toState, notes)` is called.
 */
import { useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

// Minimal lifecycle definition shapes (mirrors bookingLifecycle types)
interface LifecycleTransitionDef {
  from_state: string;
  to_state: string;
  label?: string;
  allowed_roles: string[];
}

interface LifecycleStateDef {
  key: string;
  label: string;
  is_terminal?: boolean;
}

interface LifecycleDefinition {
  states?: LifecycleStateDef[];
  transitions: LifecycleTransitionDef[];
  field_permissions?: Record<
    string,
    {
      standard_fields?: Record<string, { editable_by: string[] }>;
      custom_fields?: Record<string, { editable_by: string[] }>;
      required_fields?: string[];
    }
  >;
}

interface Props {
  currentState: string;
  userRole: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  lifecycleDefinition: any; // the full lifecycle JSON from the backend
  recordValues: Record<string, unknown> & { custom_fields?: Record<string, unknown> };
  onTransition: (toState: string, notes?: string) => Promise<void>;
}

// ----- client-side port of lifecycle_service.validate_transition -----

type ValidationResult = { allowed: true } | { allowed: false; reason: string };

function validateTransition(
  definition: LifecycleDefinition,
  fromState: string,
  toState: string,
  userRole: string,
  recordValues: Record<string, unknown> & { custom_fields?: Record<string, unknown> }
): ValidationResult {
  const transition = (definition.transitions ?? []).find(
    (t) => t.from_state === fromState && t.to_state === toState
  );
  if (!transition) {
    return { allowed: false, reason: `No transition from '${fromState}' to '${toState}' is defined` };
  }
  if (!transition.allowed_roles.includes(userRole)) {
    return {
      allowed: false,
      reason: `Role '${userRole}' is not allowed to transition ${fromState} → ${toState}`,
    };
  }

  const required: string[] =
    definition.field_permissions?.[toState]?.required_fields ?? [];

  if (required.length > 0) {
    const customValues = recordValues.custom_fields ?? {};
    const missing: string[] = [];
    for (const key of required) {
      const v = key in recordValues ? recordValues[key] : (customValues as Record<string, unknown>)[key];
      if (v === null || v === undefined || (typeof v === 'string' && v.trim() === '')) {
        missing.push(key);
      }
    }
    if (missing.length > 0) {
      return {
        allowed: false,
        reason: `Required fields empty for '${toState}': ${missing.join(', ')}`,
      };
    }
  }

  return { allowed: true };
}

// ----- Component -----

export default function TransitionControls({
  currentState,
  userRole,
  lifecycleDefinition,
  recordValues,
  onTransition,
}: Props) {
  const [pendingState, setPendingState] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const definition = lifecycleDefinition as LifecycleDefinition;

  // All transitions that originate from the current state (regardless of role)
  const candidateTransitions = (definition.transitions ?? []).filter(
    (t) => t.from_state === currentState
  );

  if (candidateTransitions.length === 0) {
    return null;
  }

  const handleClick = (toState: string) => {
    setPendingState(toState);
    setNotes('');
  };

  const handleClose = () => {
    if (submitting) return;
    setPendingState(null);
    setNotes('');
  };

  const handleConfirm = async () => {
    if (!pendingState) return;
    setSubmitting(true);
    try {
      await onTransition(pendingState, notes.trim() || undefined);
    } finally {
      setSubmitting(false);
      setPendingState(null);
      setNotes('');
    }
  };

  const pendingLabel =
    pendingState != null
      ? (definition.states?.find((s) => s.key === pendingState)?.label ?? pendingState)
      : '';

  return (
    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
      <Typography variant="body2" color="text.secondary" sx={{ mr: 0.5 }}>
        Transition:
      </Typography>

      {candidateTransitions.map((t) => {
        const result = validateTransition(
          definition,
          currentState,
          t.to_state,
          userRole,
          recordValues
        );
        const label =
          t.label ??
          (definition.states?.find((s) => s.key === t.to_state)?.label ?? t.to_state);

        const button = (
          <Button
            key={t.to_state}
            variant="outlined"
            size="small"
            disabled={!result.allowed}
            onClick={() => result.allowed && handleClick(t.to_state)}
          >
            {label}
          </Button>
        );

        if (!result.allowed) {
          return (
            <Tooltip key={t.to_state} title={result.reason} arrow>
              <span>{button}</span>
            </Tooltip>
          );
        }

        return button;
      })}

      {/* Notes dialog */}
      <Dialog open={pendingState !== null} onClose={handleClose} maxWidth="xs" fullWidth>
        <DialogTitle>Transition to {pendingLabel}</DialogTitle>
        <DialogContent>
          <TextField
            label="Notes (optional)"
            multiline
            rows={3}
            fullWidth
            size="small"
            sx={{ mt: 1 }}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={submitting}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleConfirm} disabled={submitting}>
            Confirm
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
