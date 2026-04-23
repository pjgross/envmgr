import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, Autocomplete, TextField,
} from "@mui/material";
import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { RootState, AppDispatch } from "../../../store";
import type { ReleaseListItemResponse } from "../../../types/release";
import { fetchReleases } from "../../../store/releaseSlice";
import { requestMembership } from "../../../store/enterpriseMembershipSlice";

interface Props {
  open: boolean;
  onClose: () => void;
  enterpriseId: number;
}

export function RequestAdmissionDialog({ open, onClose, enterpriseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const projects = useSelector((s: RootState) =>
    (s.release.list ?? []).filter(
      (r: ReleaseListItemResponse) =>
        r.release_kind === "project" && r.parent_release_id == null
    )
  );
  const [pick, setPick] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) dispatch(fetchReleases({}));
  }, [open, dispatch]);

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
