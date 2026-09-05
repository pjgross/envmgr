import { useEffect, useState } from "react";
import {
  Paper, Stack, TextField, MenuItem, Button,
} from "@mui/material";
import { GridColDef } from "@mui/x-data-grid";
import { useDispatch, useSelector } from "react-redux";
import type { AppDispatch, RootState } from "../../../store";
import { fetchScopeChangeKinds } from "../../../store/scopeChangeRulesSlice";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import type { ScopeRollupItem } from "../../../types/enterpriseReport";
import type { ReleaseResponse } from "../../../types/release";
import DataTable from "../../../components/DataTable";

interface Props {
  release: ReleaseResponse;
}

interface TabChangeProps {
  onNavigateToReport?: () => void;
}

export function ScopeRollupTab({ release, onNavigateToReport }: Props & TabChangeProps) {
  const dispatch = useDispatch<AppDispatch>();
  const changeKinds = useSelector((s: RootState) => s.scopeChangeRules.kinds);

  const [rows, setRows] = useState<ScopeRollupItem[]>([]);
  const [kind, setKind] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [search, setSearch] = useState<string>("");

  useEffect(() => {
    dispatch(fetchScopeChangeKinds());
  }, [dispatch]);

  useEffect(() => {
    if (release?.id == null) return;
    const params: Record<string, string | number> = {};
    if (kind) params.change_kind = kind;
    if (statusFilter) params.status = statusFilter;
    if (search) params.search = search;
    enterpriseRollupService.scope(release.id, params).then(setRows);
  }, [release?.id, kind, statusFilter, search]);

  const cols: GridColDef[] = [
    { field: "externalKey", headerName: "Key", width: 130 },
    { field: "title", headerName: "Title", flex: 1 },
    { field: "changeKind", headerName: "Kind", width: 110 },
    { field: "externalStatus", headerName: "Status", width: 140 },
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "systemName", headerName: "System", flex: 1 },
  ];

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <TextField
          select size="small" label="Kind"
          value={kind} onChange={(e) => setKind(e.target.value)}
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">Any</MenuItem>
          {changeKinds.map((k) => (
            <MenuItem key={k} value={k}>
              {k.charAt(0).toUpperCase() + k.slice(1)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small" label="Status"
          value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
        />
        <TextField
          size="small" label="Search"
          value={search} onChange={(e) => setSearch(e.target.value)}
        />
        {onNavigateToReport && (
          <Button variant="outlined" onClick={onNavigateToReport}>
            Generate report
          </Button>
        )}
      </Stack>
      <Paper>
        <DataTable
          storageKey="enterprise-scope-rollup"
          emptyMessage="No scope items across this enterprise release."
          rows={rows.map((r) => ({ id: r.releaseChangeId, ...r }))}
          columns={cols}
          autoHeight
        />
      </Paper>
    </Stack>
  );
}
