from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict

from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.user import User
from app.services import topology_service
from app.services.system_service import get_system
from app.api.v1.schemas.system import SubSystemResponse
from app.api.v1.schemas.dependency import ComponentDependencyResponse

router = APIRouter()


class TopologyResponse(BaseModel):
    subsystems: List[SubSystemResponse]
    dependencies: List[ComponentDependencyResponse]
    external_subsystems: List[SubSystemResponse]
    external_dependencies: List[ComponentDependencyResponse]
    system_names: Dict[int, str]


@router.get("/systems/{system_id}/topology", response_model=TopologyResponse)
async def get_system_topology(
    system_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get subsystems and component dependencies for a system topology diagram,
    including cross-system dependencies and their external subsystems."""
    await get_system(db, system_id, current_user.active_tenant_id)

    subsystems, dependencies, external_subsystems, external_dependencies, system_names = (
        await topology_service.get_system_topology(
            system_id, current_user.active_tenant_id, db
        )
    )
    return TopologyResponse(
        subsystems=[SubSystemResponse.model_validate(s) for s in subsystems],
        dependencies=[ComponentDependencyResponse.model_validate(d) for d in dependencies],
        external_subsystems=[SubSystemResponse.model_validate(s) for s in external_subsystems],
        external_dependencies=[ComponentDependencyResponse.model_validate(d) for d in external_dependencies],
        system_names=system_names,
    )
