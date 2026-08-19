# backend/app/api/v1/tenant_admin_fields.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import (
    custom_field_service,
    environment_compliance_service,
    environment_lifecycle_policy_service,
    raid_config_service,
)
from app.api.v1.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    CustomFieldDefinitionResponse,
)
from app.api.v1.schemas.environment_naming_policy import (
    EnvironmentNamingPolicyPreview,
    EnvironmentNamingPolicyPreviewRequest,
    EnvironmentNamingPolicyRead,
    EnvironmentNamingPolicyUpdate,
)
from app.api.v1.schemas.lifecycle_policy import (
    DecommissionStepRead,
    DecommissionStepWrite,
    EnvironmentLifecyclePolicyRead,
    EnvironmentLifecyclePolicyUpdate,
)
from app.api.v1.schemas.raid import RaidConfigRead, RaidConfigUpdate

router = APIRouter()


@router.get("/raid-config", response_model=RaidConfigRead)
async def get_raid_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await raid_config_service.get_or_seed_config(db, current_user.active_tenant_id)


@router.put("/raid-config", response_model=RaidConfigRead)
async def update_raid_config(
    data: RaidConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await raid_config_service.update_config(
        db,
        current_user.active_tenant_id,
        probability_scale=data.probability_scale,
        impact_scale=data.impact_scale,
        rag_bands=data.rag_bands,
    )


@router.get("/environment-naming-policy", response_model=EnvironmentNamingPolicyRead)
async def get_environment_naming_policy(
    db: AsyncSession = Depends(get_db),
    # Reads are open to any tenant member; only writes are Admin. The reason an
    # environment is flagged has to be legible to whoever must fix it — B3a's
    # rule, deliberately unlike /tenant/users, which really is admin-gated.
    # Note this is the one route in this router that is NOT admin-gated.
    current_user=Depends(get_current_user),
):
    policy = await environment_compliance_service.load_policy(
        db, current_user.active_tenant_id
    )
    if policy is None:
        # A tenant that has never saved one reads as "no rule in force" rather
        # than 404 — the UI has a form to render either way, and a 404 would
        # make "not configured" indistinguishable from a broken route.
        return EnvironmentNamingPolicyRead(
            is_enabled=False,
            name_pattern=None,
            name_pattern_example=None,
            required_attributes=[],
            grace_days=14,
            effective_from=datetime.now(timezone.utc),
        )
    return policy


@router.put("/environment-naming-policy", response_model=EnvironmentNamingPolicyRead)
async def put_environment_naming_policy(
    data: EnvironmentNamingPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_compliance_service.upsert_policy(
        db,
        current_user.active_tenant_id,
        is_enabled=data.is_enabled,
        name_pattern=data.name_pattern,
        name_pattern_example=data.name_pattern_example,
        required_attributes=data.required_attributes,
        grace_days=data.grace_days,
    )


@router.post(
    "/environment-naming-policy/preview",
    response_model=EnvironmentNamingPolicyPreview,
)
async def preview_environment_naming_policy(
    data: EnvironmentNamingPolicyPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """What a policy would do, before it does it.

    ADMIN-ONLY, unlike the policy GET above which any tenant member may read: a
    preview runs a caller-supplied regex over the whole estate, so it stays with
    the people who may set the policy in the first place.

    A POST because it carries a body, not because it changes anything — it
    writes nothing. Unbounded by design, like the other rollup endpoints: it
    counts the whole estate, which is the question being asked. Listed as such
    in docs/pagination.md.
    """
    total, in_gap, quarantined, sample = (
        await environment_compliance_service.preview_policy(
            db,
            current_user.active_tenant_id,
            name_pattern=data.name_pattern,
            required_attributes=data.required_attributes,
        )
    )
    return EnvironmentNamingPolicyPreview(
        total_environments=total,
        in_gap=in_gap,
        quarantined_now=quarantined,
        sample_names=sample,
    )


@router.get(
    "/environment-lifecycle-policy", response_model=EnvironmentLifecyclePolicyRead
)
async def get_environment_lifecycle_policy(
    db: AsyncSession = Depends(get_db),
    # Reads open to any tenant member; only writes are Admin — same split as
    # the naming policy above and B3a's user groups.
    current_user=Depends(get_current_user),
):
    return await environment_lifecycle_policy_service.get_policy(
        db, current_user.active_tenant_id
    )


@router.put(
    "/environment-lifecycle-policy", response_model=EnvironmentLifecyclePolicyRead
)
async def put_environment_lifecycle_policy(
    data: EnvironmentLifecyclePolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_lifecycle_policy_service.upsert_policy(
        db,
        current_user.active_tenant_id,
        idle_detection_enabled=data.idle_detection_enabled,
        idle_threshold_days=data.idle_threshold_days,
        decommission_notice_days=data.decommission_notice_days,
    )


@router.get("/decommission-steps", response_model=list[DecommissionStepRead])
async def list_decommission_steps(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_lifecycle_policy_service.list_steps(
        db, current_user.active_tenant_id, active_only=active_only
    )


@router.post(
    "/decommission-steps",
    response_model=DecommissionStepRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decommission_step(
    data: DecommissionStepWrite,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_lifecycle_policy_service.create_step(
        db,
        current_user.active_tenant_id,
        key=data.key,
        label=data.label,
        description=data.description,
        display_order=data.display_order,
        is_required=data.is_required,
        is_active=data.is_active,
    )


@router.patch("/decommission-steps/{step_id}", response_model=DecommissionStepRead)
async def update_decommission_step(
    step_id: int,
    data: DecommissionStepWrite,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_lifecycle_policy_service.update_step(
        db,
        step_id,
        current_user.active_tenant_id,
        key=data.key,
        label=data.label,
        description=data.description,
        display_order=data.display_order,
        is_required=data.is_required,
        is_active=data.is_active,
    )


@router.delete("/decommission-steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decommission_step(
    step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_lifecycle_policy_service.delete_step(
        db, step_id, current_user.active_tenant_id
    )


@router.get("/fields", response_model=list[CustomFieldDefinitionResponse])
async def list_fields(
    entity_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.list_definitions(db, current_user.active_tenant_id, entity_type)


@router.post("/fields", response_model=CustomFieldDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_field(
    data: CustomFieldDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.create_definition(db, current_user.active_tenant_id, data)


@router.patch("/fields/{field_id}", response_model=CustomFieldDefinitionResponse)
async def update_field(
    field_id: int,
    data: CustomFieldDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.update_definition(db, current_user.active_tenant_id, field_id, data)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await custom_field_service.delete_definition(db, current_user.active_tenant_id, field_id)
