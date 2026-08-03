"""Terraform HCL detector."""
from app.services import terraform_hcl_import_service
from app.services.scanning.registry import Detector, DetectorResult, ParseContext


def _matches(path: str) -> bool:
    # .tfstate and .tfvars are deliberately excluded: state is not normally
    # committed, and tfvars is configuration rather than resource declarations.
    return path.endswith(".tf")


async def _parse(ctx: ParseContext) -> DetectorResult:
    result = await terraform_hcl_import_service.import_terraform_hcl(
        system_id=ctx.system_id, tenant_id=ctx.tenant_id,
        content=ctx.content, db=ctx.db,
    )
    return DetectorResult(
        subsystems_created=result["subsystems_created"],
        subsystems_updated=result["subsystems_updated"],
    )


TERRAFORM_HCL = Detector(name="terraform_hcl", matches=_matches, parse=_parse)
