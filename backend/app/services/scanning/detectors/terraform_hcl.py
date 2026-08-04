"""Terraform HCL detector."""
from app.db.models.system import SubSystemSource
from app.services import terraform_hcl_import_service
from app.services.scanning.declared import DeclaredState
from app.services.scanning.registry import Detector, ParseContext


def _matches(path: str) -> bool:
    # .tfstate and .tfvars are deliberately excluded: state is not normally
    # committed, and tfvars is configuration rather than resource declarations.
    return path.endswith(".tf")


async def _parse(ctx: ParseContext) -> DeclaredState:
    return terraform_hcl_import_service.parse_terraform_hcl(ctx.content, ctx.path)


TERRAFORM_HCL = Detector(
    name="terraform_hcl",
    matches=_matches,
    parse=_parse,
    subsystem_source=SubSystemSource.TERRAFORM_HCL,
    # HCL wires dependencies through interpolations, which this does not read.
    edge_source=None,
)
