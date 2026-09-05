import { useEffect, useState } from "react";
import { Paper, Chip, Stack } from "@mui/material";
import { GridColDef } from "@mui/x-data-grid";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import DataTable from "../../../components/DataTable";
import type { ReleaseResponse } from "../../../types/release";
import type { SystemRollupRow } from "../../../types/enterpriseReport";

interface Props {
  release: ReleaseResponse;
}

export function SystemsRollupTab({ release }: Props) {
  const [rows, setRows] = useState<SystemRollupRow[]>([]);

  useEffect(() => {
    if (release?.id == null) return;
    enterpriseRollupService.systems(release.id).then(setRows);
  }, [release?.id]);

  const cols: GridColDef[] = [
    { field: "systemName", headerName: "System", flex: 1 },
    {
      field: "rolesByProject",
      headerName: "Roles by project",
      flex: 2,
      renderCell: ({ value }) => (
        <Stack direction="row" spacing={1} flexWrap="wrap">
          {Object.entries((value ?? {}) as Record<string, string[]>).map(([proj, roles]) => (
            <Chip key={proj} label={`${proj}: ${roles.join(", ")}`} size="small" />
          ))}
        </Stack>
      ),
      sortable: false,
    },
  ];

  return (
    <Paper>
      <DataTable
        storageKey="enterprise-systems-rollup"
        emptyMessage="No systems across this enterprise release."
        rows={rows.map((r) => ({ id: r.systemId, ...r }))}
        columns={cols}
        autoHeight
        hideFooter
      />
    </Paper>
  );
}
