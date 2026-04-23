import { useEffect, useState } from "react";
import {
  Paper, Stack, Typography, Button, Chip, IconButton,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { useDispatch, useSelector } from "react-redux";
import type { RootState, AppDispatch } from "../../../store";
import type { ReleaseResponse } from "../../../types/release";
import {
  fetchMemberships,
  acceptMembership,
  rejectMembership,
  removeMembership,
} from "../../../store/enterpriseMembershipSlice";
import { useConfirm } from "../../../hooks/useConfirm";
import { RequestAdmissionDialog } from "./RequestAdmissionDialog";

interface Props {
  release: ReleaseResponse;
}

export function MembersTab({ release }: Props) {
  const releaseId = release.id;
  const dispatch = useDispatch<AppDispatch>();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const rows = useSelector((s: RootState) => s.enterpriseMembership.byEnterprise[releaseId] ?? []);
  const [openRequest, setOpenRequest] = useState(false);

  useEffect(() => {
    dispatch(fetchMemberships({ enterpriseId: releaseId }));
  }, [dispatch, releaseId]);

  const pending = rows.filter((r) => r.state === "pending_request");
  const accepted = rows.filter((r) => r.state === "accepted");
  const history = rows.filter((r) => !["pending_request", "accepted"].includes(r.state));

  const pendingCols: GridColDef[] = [
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "requestedByUsername", headerName: "Requested by", flex: 1 },
    {
      field: "requestedAt", headerName: "Requested", flex: 1,
      valueFormatter: (p: { value?: string | null }) =>
        p?.value ? new Date(p.value).toLocaleString() : "",
    },
    {
      field: "actions", headerName: "Actions", width: 240, sortable: false,
      renderCell: ({ row }) => (
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="contained"
            onClick={() =>
              dispatch(acceptMembership({ enterpriseId: releaseId, membershipId: row.id }))
            }
          >
            Accept
          </Button>
          <Button
            size="small"
            color="error"
            onClick={async () => {
              const notes = prompt("Reason for rejection?");
              if (notes) {
                dispatch(rejectMembership({
                  enterpriseId: releaseId,
                  membershipId: row.id,
                  notes,
                }));
              }
            }}
          >
            Reject
          </Button>
        </Stack>
      ),
    },
  ];

  const acceptedCols: GridColDef[] = [
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    {
      field: "projectReleaseStatus", headerName: "Status", width: 140,
      renderCell: ({ value }) => value ? <Chip label={value} size="small" /> : null,
    },
    {
      field: "decidedAt", headerName: "Admitted", flex: 1,
      valueFormatter: (p: { value?: string | null }) =>
        p?.value ? new Date(p.value).toLocaleString() : "",
    },
    {
      field: "lateScope", headerName: "Late", width: 90,
      renderCell: ({ value }) =>
        value ? <Chip label="LATE" color="warning" size="small" /> : null,
    },
    {
      field: "actions", headerName: "", width: 80, sortable: false,
      renderCell: ({ row }) => (
        <IconButton
          size="small"
          color="error"
          onClick={async () => {
            const ok = await confirm({
              title: "Remove project from enterprise?",
              message: `This will detach ${row.projectReleaseName} from the enterprise release.`,
              confirmLabel: "Remove",
              destructive: true,
            });
            if (!ok) return;
            const reason = prompt("Reason?") ?? "removed";
            dispatch(removeMembership({
              enterpriseId: releaseId,
              membershipId: row.id,
              reason,
            }));
          }}
        >
          <DeleteIcon />
        </IconButton>
      ),
    },
  ];

  const historyCols: GridColDef[] = [
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "state", headerName: "State", width: 120 },
    {
      field: "decidedAt", headerName: "Decided at", flex: 1,
      valueFormatter: (p: { value?: string | null }) =>
        p?.value ? new Date(p.value).toLocaleString() : "",
    },
    { field: "removalReason", headerName: "Reason", flex: 1 },
  ];

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h6">Pending requests</Typography>
        <Button variant="contained" onClick={() => setOpenRequest(true)}>
          Request admission…
        </Button>
      </Stack>
      <Paper>
        <DataGrid rows={pending} columns={pendingCols} autoHeight hideFooter />
      </Paper>

      <Typography variant="h6">Accepted members</Typography>
      <Paper>
        <DataGrid rows={accepted} columns={acceptedCols} autoHeight hideFooter />
      </Paper>

      <Typography variant="h6">History</Typography>
      <Paper>
        <DataGrid rows={history} columns={historyCols} autoHeight hideFooter />
      </Paper>

      <RequestAdmissionDialog
        open={openRequest}
        onClose={() => setOpenRequest(false)}
        enterpriseId={releaseId}
      />

      {confirmDialog}
    </Stack>
  );
}
