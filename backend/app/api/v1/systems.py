from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db, AsyncSessionLocal
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.system import System
from app.services import rollback_rehearsal_service, system_service, tenant_secret_service
from app.services.github_client import (
    GitHubAuthError,
    GitHubNotFound,
    GitHubRateLimited,
    GitHubUnavailable,
    GitHubUnexpectedResponse,
)
from app.services.github_oauth_service import TOKEN_KIND, LOGIN_KIND
from app.services.scanning import scanner
from app.services.scanning.scanner import ScanAlreadyRunning
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.api.v1.schemas.system import (
    SystemCreate,
    SystemUpdate,
    SystemResponse,
    SubSystemCreate,
    SubSystemUpdate,
    SubSystemResponse,
)
from app.api.v1.schemas.rollback import RehearsalCreate, RehearsalRead

router = APIRouter()


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------


SYSTEM_SORTS = {
    "name": System.name,
}


@router.get("/", response_model=list[SystemResponse])
async def list_systems(
    response: Response,
    search: Optional[str] = None,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(SYSTEM_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await system_service.list_systems(
        db, current_user.active_tenant_id, page=page, search=search, sort=sort
    )
    set_total_count(response, total)
    return rows


@router.post("/", response_model=SystemResponse, status_code=status.HTTP_201_CREATED)
async def create_system(
    data: SystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.create_system(db, data, current_user.active_tenant_id)


@router.get("/{system_id}", response_model=SystemResponse)
async def get_system(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.get_system(db, system_id, current_user.active_tenant_id)


@router.patch("/{system_id}", response_model=SystemResponse)
async def update_system(
    system_id: int,
    data: SystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.update_system(db, system_id, data, current_user.active_tenant_id)


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await system_service.delete_system(db, system_id, current_user.active_tenant_id)


@router.post("/{system_id}/github/scan")
async def scan_system_repository(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Scan the system's GitHub repository and import what the detectors find."""
    tenant_id = current_user.active_tenant_id
    system = await system_service.get_system(db, system_id, tenant_id)

    token = await tenant_secret_service.get_secret(db, tenant_id, TOKEN_KIND)
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "GitHub is not connected for this tenant. Connect it under "
            "Administration → GitHub Integration.",
        )

    try:
        return await scanner.scan_repository(
            db, token=token, system_id=system_id, tenant_id=tenant_id,
            repo_url=system.github_repository_url,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except ScanAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except GitHubAuthError:
        # Clear it so the UI stops claiming "connected" with a dead token.
        #
        # This must happen in its own session: get_db commits on success and
        # rolls back on any exception (see app/db/base.py), and this branch
        # raises HTTPException on its way out. A delete on `db` here would be
        # silently discarded by that rollback, leaving the dead token in
        # place forever — every future scan would 401 again with the UI still
        # reporting "connected". Following the same pattern as
        # app/workers/event_publisher.py for a write that must survive.
        async with AsyncSessionLocal() as cleanup:
            await tenant_secret_service.delete_secret(cleanup, tenant_id, TOKEN_KIND)
            await tenant_secret_service.delete_secret(cleanup, tenant_id, LOGIN_KIND)
            await cleanup.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "GitHub rejected the stored token. Reconnect the integration.",
        )
    except GitHubRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"GitHub API rate limit exceeded. Resets at {exc.reset_at}.",
        )
    except GitHubNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except (GitHubUnavailable, GitHubUnexpectedResponse) as exc:
        # Neither is the caller's fault or fixable by retrying the same
        # request immediately — 502 says "the upstream (GitHub) misbehaved",
        # not "your request was wrong" or "try again in a bit" (429).
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/{system_id}/github/drift")
async def system_repository_drift(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Report where the subsystem catalogue and the repository disagree.

    Read-only. Gated the same as the scan: it reads repository contents through
    the tenant's stored token, so it must not be looser than the write that
    does the same thing.
    """
    tenant_id = current_user.active_tenant_id
    system = await system_service.get_system(db, system_id, tenant_id)

    token = await tenant_secret_service.get_secret(db, tenant_id, TOKEN_KIND)
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "GitHub is not connected for this tenant. Connect it under "
            "Administration → GitHub Integration.",
        )

    try:
        return await scanner.drift_repository(
            db, token=token, system_id=system_id, tenant_id=tenant_id,
            repo_url=system.github_repository_url,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except ScanAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except GitHubAuthError:
        # Its own session: get_db rolls back on the HTTPException raised below,
        # which would silently discard a delete on `db` and leave the dead
        # token in place forever. Same reasoning as the scan endpoint above.
        async with AsyncSessionLocal() as cleanup:
            await tenant_secret_service.delete_secret(cleanup, tenant_id, TOKEN_KIND)
            await tenant_secret_service.delete_secret(cleanup, tenant_id, LOGIN_KIND)
            await cleanup.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "GitHub rejected the stored token. Reconnect the integration.",
        )
    except GitHubRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"GitHub API rate limit exceeded. Resets at {exc.reset_at}.",
        )
    except GitHubNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except (GitHubUnavailable, GitHubUnexpectedResponse) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


# ---------------------------------------------------------------------------
# SubSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{system_id}/subsystems", response_model=list[SubSystemResponse])
async def list_subsystems(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.list_subsystems(db, system_id, current_user.active_tenant_id)


@router.post(
    "/{system_id}/subsystems",
    response_model=SubSystemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subsystem(
    system_id: int,
    data: SubSystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.create_subsystem(
        db, system_id, data, current_user.active_tenant_id
    )


@router.get("/{system_id}/subsystems/{sub_id}", response_model=SubSystemResponse)
async def get_subsystem(
    system_id: int,
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.get_subsystem(
        db, sub_id, system_id, current_user.active_tenant_id
    )


@router.patch("/{system_id}/subsystems/{sub_id}", response_model=SubSystemResponse)
async def update_subsystem(
    system_id: int,
    sub_id: int,
    data: SubSystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.update_subsystem(
        db, sub_id, system_id, data, current_user.active_tenant_id
    )


@router.delete("/{system_id}/subsystems/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subsystem(
    system_id: int,
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await system_service.delete_subsystem(
        db, sub_id, system_id, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# Rollback rehearsal endpoints (Phase 9 C4 Task 4)
# ---------------------------------------------------------------------------
# Registered after every existing `/{system_id}` and `/{system_id}/...` route
# in this file. `GET/PATCH/DELETE /{system_id}` has no trailing path segment,
# so it cannot swallow a literal segment the way B6's `/{booking_id}`
# catch-all swallowed `/contention-horizon` (same segment count, competing
# for the same slot) — the routes below add an extra segment, which is a
# different match entirely. Verified by the HTTP round-trip test in
# tests/integration/test_rollback_rehearsal_api.py, not by this reasoning
# alone.


@router.get(
    "/{system_id}/rollback-rehearsals", response_model=list[RehearsalRead]
)
async def list_rollback_rehearsals(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    rehearsals = await rollback_rehearsal_service.list_rehearsals(db, system_id, tenant_id)
    return await rollback_rehearsal_service.reads_for_rehearsals(db, tenant_id, rehearsals)


@router.post(
    "/{system_id}/rollback-rehearsals",
    response_model=RehearsalRead,
    status_code=status.HTTP_201_CREATED,
)
async def record_rollback_rehearsal(
    system_id: int,
    data: RehearsalCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    rehearsal = await rollback_rehearsal_service.record_rehearsal(
        db, system_id, tenant_id, current_user.id, data
    )
    reads = await rollback_rehearsal_service.reads_for_rehearsals(db, tenant_id, [rehearsal])
    return reads[0]
