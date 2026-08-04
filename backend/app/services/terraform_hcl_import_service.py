"""Import Terraform .tf source (HCL) as SubSystems.

Distinct from terraform_import_service, which parses .tfstate. HCL gives
DECLARED resources — no computed values, no resource ids — so this and a
tfstate import of the same infrastructure will not produce identical rows.
Naming is `<type>.<name>`, the address Terraform itself uses.
"""
import io

import hcl2
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scanning.declared import DeclaredState, DeclaredSubsystem
from app.services.terraform_import_service import infer_component_type


def parse_terraform_hcl(content: bytes, path: str) -> DeclaredState:
    """Read .tf source into the resources it declares. Pure — no database."""
    declared = DeclaredState()
    if not content.strip():
        return declared

    try:
        parsed = hcl2.load(io.StringIO(content.decode("utf-8")))
    except Exception as exc:  # hcl2 raises a variety of parser errors
        raise ValueError(f"Invalid Terraform HCL: {exc}") from exc

    # Only `resource` blocks are infrastructure to inventory. hcl2.load returns
    # parsed["resource"] as a list of single-key dicts:
    # {resource_type: {resource_name: {...body}}}.
    for block in parsed.get("resource", []) or []:
        if not isinstance(block, dict):
            declared.warnings.append("skipped a resource block that was not a mapping")
            continue
        for resource_type, bodies in block.items():
            if not isinstance(bodies, dict):
                declared.warnings.append(
                    f"skipped malformed resource block {resource_type!r}"
                )
                continue
            for name, body in bodies.items():
                # A real resource's value is its BODY — a dict. A `resource`
                # block missing its name label parses so that the resource's own
                # attributes sit here instead, and taking these keys as names
                # fabricates one bogus subsystem per attribute while reporting
                # success.
                if not isinstance(body, dict):
                    declared.warnings.append(
                        f"skipped {resource_type!r}: block appears to be missing "
                        "its name label"
                    )
                    continue
                declared.subsystems.append(DeclaredSubsystem(
                    name=f"{resource_type}.{name}"[:200],
                    component_type=infer_component_type(resource_type),
                    technology=resource_type[:100],
                    source_path=path[:500],
                ))

    return declared


async def import_terraform_hcl(
    system_id: int, tenant_id: int, content: bytes, db: AsyncSession,
    path: str = "main.tf",
) -> dict:
    """Parse .tf source and write what it declares.

    No production caller today — import_routes.py wires up its siblings
    import_docker_compose and import_terraform (the .tfstate importer) but
    not this one. Kept anyway: it is the symmetric third of that trio, for
    an upload-based HCL path someone will want later.
    """
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_terraform_hcl(content, path)
    result = await reconcile.apply(
        db, system_id=system_id, tenant_id=tenant_id,
        source=SubSystemSource.TERRAFORM_HCL,
        # HCL declares no edges, so nothing may be deleted on its behalf.
        edge_source=None,
        declared=declared,
    )
    return {
        "subsystems_created": result.subsystems_created,
        "subsystems_updated": result.subsystems_updated,
        "warnings": declared.warnings,
    }
