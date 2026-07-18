"""Scope import service — imports release scope items (ReleaseChange) from .xlsx.

Upserts on (release_id, external_key) when an external_key is present; otherwise
inserts. Sets source='spreadsheet'. No per-row events (bulk import).
"""
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.version import ImportError
from app.db.models.release_change import ReleaseChange

_COLUMNS = ["external_key", "title", "description", "change_kind",
            "external_status", "project_code", "project_name"]


def _header_index(headers: list, name: str, required: bool) -> Optional[int]:
    lower = name.lower()
    for i, h in enumerate(headers):
        if h is not None and str(h).strip().lower() == lower:
            return i
    if required:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing required column: '{name}'")
    return None


def _cell(row: tuple, idx: Optional[int]) -> Optional[str]:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None


async def import_scope(
    db: AsyncSession, file_bytes: bytes, release_id: int, tenant_id: int
) -> dict:
    try:
        wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not read spreadsheet")
    ws = wb.active
    headers = [c.value for c in ws[1]]
    idx = {c: _header_index(headers, c, required=(c in ("title", "change_kind"))) for c in _COLUMNS}

    created = updated = 0
    errors: list[ImportError] = []

    for rownum, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row is None or all(v is None for v in row):
            continue
        title = _cell(row, idx["title"])
        kind = _cell(row, idx["change_kind"])
        if not title:
            errors.append(ImportError(row=rownum, field="title", message="title is required"))
            continue
        if not kind:
            errors.append(ImportError(row=rownum, field="change_kind", message="change_kind is required"))
            continue
        ek = _cell(row, idx["external_key"])

        existing = None
        if ek:
            existing = (await db.execute(
                select(ReleaseChange).where(
                    ReleaseChange.tenant_id == tenant_id,
                    ReleaseChange.release_id == release_id,
                    ReleaseChange.external_key == ek,
                    ReleaseChange.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

        fields = dict(
            title=title, change_kind=kind,
            description=_cell(row, idx["description"]),
            external_status=_cell(row, idx["external_status"]),
            project_code=_cell(row, idx["project_code"]),
            project_name=_cell(row, idx["project_name"]),
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.source = "spreadsheet"
            updated += 1
        else:
            db.add(ReleaseChange(
                tenant_id=tenant_id, release_id=release_id, external_key=ek,
                source="spreadsheet", **fields,
            ))
            created += 1

    await db.flush()
    return {"created": created, "updated": updated, "errors": errors}
