"""Import Terraform .tf source (HCL) as SubSystems.

Distinct from terraform_import_service, which parses .tfstate. HCL gives
DECLARED resources — no computed values, no resource ids — so this and a
tfstate import of the same infrastructure will not produce identical rows.
Naming is `<type>.<name>`, the address Terraform itself uses.
"""
import io

import hcl2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system import SubSystem


async def import_terraform_hcl(
    system_id: int, tenant_id: int, content: bytes, db: AsyncSession
) -> dict:
    if not content.strip():
        return {"subsystems_created": 0, "subsystems_updated": 0, "warnings": []}

    try:
        parsed = hcl2.load(io.StringIO(content.decode("utf-8")))
    except Exception as exc:  # hcl2 raises a variety of parser errors
        raise ValueError(f"Invalid Terraform HCL: {exc}") from exc

    # Only `resource` blocks are infrastructure to inventory; variable,
    # output, provider and locals are not. hcl2.load returns parsed["resource"]
    # as a list of single-key dicts: {resource_type: {resource_name: {...body}}}.
    addresses: list[str] = []
    warnings: list[str] = []
    for block in parsed.get("resource", []) or []:
        if not isinstance(block, dict):
            warnings.append("skipped a resource block that was not a mapping")
            continue
        for resource_type, bodies in block.items():
            if not isinstance(bodies, dict):
                warnings.append(f"skipped malformed resource block {resource_type!r}")
                continue
            for name, body in bodies.items():
                # A real resource's value is its BODY — a dict. A `resource`
                # block missing its name label parses so that the resource's
                # own attributes sit here instead, and taking these keys as
                # names fabricates one bogus subsystem per attribute while
                # reporting success.
                if not isinstance(body, dict):
                    warnings.append(
                        f"skipped {resource_type!r}: block appears to be missing "
                        "its name label"
                    )
                    continue
                addresses.append(f"{resource_type}.{name}")

    existing = {
        s.name: s
        for s in (await db.execute(
            select(SubSystem).where(
                SubSystem.system_id == system_id,
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )).scalars().all()
    }

    created = updated = 0
    for address in addresses:
        if address in existing:
            updated += 1
            continue
        db.add(SubSystem(tenant_id=tenant_id, system_id=system_id, name=address))
        created += 1
    await db.flush()
    return {
        "subsystems_created": created,
        "subsystems_updated": updated,
        "warnings": warnings,
    }
