from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_type import GateTypeCreate, GateTypeRead, GateTypeUpdate
from app.core.pagination import Page, Sort, pagination, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.gate_type import GateType
from app.services import gate_type_service

router = APIRouter()

GATE_TYPE_SORTS = {
    "name": GateType.name,
    "display_order": GateType.display_order,
    "category": GateType.category,
}


@router.get("", response_model=list[GateTypeRead])
async def list_gate_types(
    response: Response,
    include_inactive: bool = True,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(GATE_TYPE_SORTS, "display_order")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Reads are open to ANY tenant member; only writes are Admin.

    Deliberately unlike /tenant/users, which really is admin-gated. B3a shipped
    this over-gated on exactly that false analogy and it took a review to catch.
    """
    rows, total = await gate_type_service.list_types(
        db, current_user.active_tenant_id, page=page, sort=sort,
        include_inactive=include_inactive,
    )
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.post("", response_model=GateTypeRead, status_code=status.HTTP_201_CREATED)
async def create_gate_type(
    data: GateTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await gate_type_service.create_type(db, current_user.active_tenant_id, data)


@router.put("/{type_id}", response_model=GateTypeRead)
async def update_gate_type(
    type_id: int,
    data: GateTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await gate_type_service.update_type(
        db, type_id, current_user.active_tenant_id, data
    )


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await gate_type_service.delete_type(db, type_id, current_user.active_tenant_id)
