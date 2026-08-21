/**
 * GateEvidenceList — the evidence attached to one gate: a test report, a
 * runbook, a licence document, ... optionally naming the deployment it was
 * produced against.
 *
 * Stale evidence (its cited deployment has since been superseded by a
 * later deployment to the same environment — see
 * `gate_evidence_service.stale_evidence_ids` on the backend) is marked
 * visibly with a "Superseded" chip rather than hidden: an evidence row
 * disappearing would read as "no evidence was ever added", which is a
 * worse lie than an evidence row that plainly says it is out of date.
 */
import { useMemo } from 'react';
import {
  Box,
  Chip,
  IconButton,
  Link,
  List,
  ListItem,
  ListItemText,
  Tooltip,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useReleaseDeployments } from '../../hooks/useReleaseDeployments';
import { formatDeploymentLabel } from '../../utils/deploymentLabel';
import type { GateEvidenceResponse } from '../../types/gateEvidence';

interface Props {
  releaseId: number;
  evidence: GateEvidenceResponse[];
  onDelete: (evidence: GateEvidenceResponse) => void;
}

export default function GateEvidenceList({ releaseId, evidence, onDelete }: Props) {
  const { deployments } = useReleaseDeployments(releaseId);
  const deploymentById = useMemo(
    () => new Map(deployments.map((d) => [d.id, d])),
    [deployments]
  );

  if (evidence.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ pl: 4, py: 1 }}>
        No evidence attached.
      </Typography>
    );
  }

  return (
    <List dense disablePadding sx={{ pl: 2 }}>
      {evidence.map((item) => {
        const deployment = item.deployment_id != null ? deploymentById.get(item.deployment_id) : undefined;
        const deploymentLabel = item.deployment_id == null
          ? null
          : deployment
            ? formatDeploymentLabel(deployment)
            : `Deployment #${item.deployment_id}`;

        return (
          <ListItem
            key={item.id}
            secondaryAction={
              <Tooltip title="Delete evidence">
                <IconButton
                  size="small"
                  aria-label={`Delete evidence ${item.label}`}
                  onClick={() => onDelete(item)}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            }
          >
            <ListItemText
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Chip size="small" variant="outlined" label={item.kind} />
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>
                    {item.label}
                  </Typography>
                  {item.url && (
                    <Link
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      variant="body2"
                      sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.25 }}
                    >
                      Open <OpenInNewIcon sx={{ fontSize: 14 }} />
                    </Link>
                  )}
                  {item.is_stale && (
                    <Chip size="small" color="warning" label="Superseded" />
                  )}
                </Box>
              }
              secondary={
                deploymentLabel
                  ? `Deployment: ${deploymentLabel}`
                  : 'No deployment linked'
              }
            />
          </ListItem>
        );
      })}
    </List>
  );
}
