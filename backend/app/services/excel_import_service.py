"""
Excel import service — imports environments and systems from .xlsx files.
"""
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.system import System
from app.api.v1.schemas.environment import EnvironmentCreate
from app.services import environment_service, system_service


def _find_col(headers: list, name: str, required: bool = True) -> Optional[int]:
    """Return the 0-based column index matching *name* (case-insensitive).

    Raises HTTP 400 when required=True and the column is missing.
    """
    lower = name.lower()
    for i, h in enumerate(headers):
        if h is not None and str(h).strip().lower() == lower:
            return i
    if required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required column: '{name}'",
        )
    return None


async def import_environments(
    db: AsyncSession, file_bytes: bytes, tenant_id: int
) -> dict:
    """
    Parse an Excel workbook and import environments.

    Required columns: Name, Type
    Optional columns: Description, Status
    """
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    headers = [cell.value for cell in ws[1]]  # first row = headers

    name_idx = _find_col(headers, "Name", required=True)
    type_idx = _find_col(headers, "Type", required=False)
    desc_idx = _find_col(headers, "Description", required=False)

    errors: list[dict] = []
    created = 0
    skipped = 0

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        # Skip completely empty rows
        if all(cell is None for cell in row):
            continue

        name = row[name_idx] if name_idx is not None and name_idx < len(row) else None
        if not name or str(name).strip() == "":
            errors.append({"row": row_num, "field": "Name", "message": "Name is required"})
            continue

        name_str = str(name).strip()

        env_type = (
            str(row[type_idx]).strip()
            if type_idx is not None and type_idx < len(row) and row[type_idx] is not None
            else "imported"
        )
        description = (
            str(row[desc_idx]).strip()
            if desc_idx is not None and desc_idx < len(row) and row[desc_idx] is not None
            else None
        )

        # Check if env already exists (skip if so)
        existing_result = await db.execute(
            select(Environment).where(
                Environment.name == name_str,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue

        try:
            data = EnvironmentCreate(
                name=name_str,
                environment_type=env_type if env_type else "imported",
                description=description or None,
            )
            await environment_service.create_environment(db, data, tenant_id)
            created += 1
        except Exception as e:
            errors.append({"row": row_num, "field": "general", "message": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}


async def import_systems(
    db: AsyncSession, file_bytes: bytes, tenant_id: int
) -> dict:
    """
    Parse an Excel workbook and import systems.

    Required columns: Name
    Optional columns: Description, GitHub URL
    """
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    ws = wb.active

    headers = [cell.value for cell in ws[1]]  # first row = headers

    name_idx = _find_col(headers, "Name", required=True)
    desc_idx = _find_col(headers, "Description", required=False)
    github_idx = _find_col(headers, "GitHub URL", required=False)

    errors: list[dict] = []
    created = 0
    skipped = 0

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        # Skip completely empty rows
        if all(cell is None for cell in row):
            continue

        name = row[name_idx] if name_idx is not None and name_idx < len(row) else None
        if not name or str(name).strip() == "":
            errors.append({"row": row_num, "field": "Name", "message": "Name is required"})
            continue

        name_str = str(name).strip()

        description = (
            str(row[desc_idx]).strip()
            if desc_idx is not None and desc_idx < len(row) and row[desc_idx] is not None
            else None
        )
        github_url = (
            str(row[github_idx]).strip()
            if github_idx is not None and github_idx < len(row) and row[github_idx] is not None
            else None
        )

        # Check if system already exists (skip if so)
        existing_result = await db.execute(
            select(System).where(
                System.name == name_str,
                System.tenant_id == tenant_id,
                System.deleted_at.is_(None),
            )
        )
        if existing_result.scalar_one_or_none():
            skipped += 1
            continue

        try:
            from app.api.v1.schemas.system import SystemCreate
            data = SystemCreate(
                name=name_str,
                description=description or None,
                github_repository_url=github_url or None,
            )
            await system_service.create_system(db, data, tenant_id)
            created += 1
        except Exception as e:
            errors.append({"row": row_num, "field": "general", "message": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}
