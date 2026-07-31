import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Autocomplete, TextField, FormHelperText,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import type { AppDispatch } from "../../../store";
import type { ReleaseListItemResponse } from "../../../types/release";
import { requestMembership } from "../../../store/enterpriseMembershipSlice";
import { useSnackbar } from "../../../hooks/useSnackbar";
import { releaseService } from "../../../services/releaseService";

interface Props {
  open: boolean;
  onClose: () => void;
  enterpriseId: number;
}

export function RequestAdmissionDialog({ open, onClose, enterpriseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const [releases, setReleases] = useState<ReleaseListItemResponse[]>([]);
  const [releaseTotal, setReleaseTotal] = useState(0);
  const [pick, setPick] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  // This dialog needs its own copy of the project-release list rather than
  // reading `state.release.list` — that slice is now the Releases tab's
  // current filtered/sorted server-side page (25 rows by default), so
  // whatever filter the user left active there would silently narrow the
  // "Project release" options here too, with nothing indicating anything is
  // missing. Fetched directly into local state on every open, unconditionally,
  // so it never depends on — or overwrites — the shared slice. `release_kind`
  // is filtered server-side; `parent_release_id == null` has no server-side
  // filter param, so it stays a client-side filter over the fetched page.
  useEffect(() => {
    if (open) {
      setPick(null);
      setNotes("");
      releaseService
        .list({ release_kind: "project", limit: 200 })
        .then(({ rows, total }) => {
          setReleases(rows);
          setReleaseTotal(total);
        })
        .catch((err) => {
          setReleases([]);
          setReleaseTotal(0);
          snackbar.error(
            err instanceof Error ? err.message : "Failed to load releases"
          );
        });
    }
    // `snackbar` is a fresh object every render (see useSnackbar) — adding
    // it here would refire this effect, and refetch releases, on every
    // render rather than only on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const projects = releases.filter(
    (r) => r.release_kind === "project" && r.parent_release_id == null
  );

  const handleSubmit = async () => {
    if (!pick) return;
    await dispatch(requestMembership({
      enterpriseId,
      projectReleaseId: pick,
      notes: notes || undefined,
    }));
    setPick(null);
    setNotes("");
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Request admission</DialogTitle>
      <DialogContent>
        <Autocomplete
          options={projects}
          getOptionLabel={(o: ReleaseListItemResponse) => o.name}
          onChange={(_, v) => setPick(v?.id ?? null)}
          renderInput={(p) => (
            <TextField {...p} label="Project release" margin="normal" />
          )}
        />
        {releaseTotal > releases.length && (
          <FormHelperText sx={{ mt: -1.5, mb: 1 }}>
            Only the first {releases.length} of {releaseTotal} releases are shown.
          </FormHelperText>
        )}
        <TextField
          fullWidth
          multiline
          rows={2}
          margin="normal"
          label="Notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          disabled={!pick}
          variant="contained"
          onClick={handleSubmit}
        >
          Request
        </Button>
      </DialogActions>
    </Dialog>
  );
}
