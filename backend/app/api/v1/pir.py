"""PIR (Post-Implementation Review) endpoints — one PIR per release.

Routes: /releases/{release_id}/pir  (GET / POST / PATCH / DELETE)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import pir_service, pir_finding_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate, PIRResponse
from app.api.v1.schemas.pir_finding import (
    PirActionCreate,
    PirActionResponse,
    PirActionUpdate,
    PirCitationCreate,
    PirCitationResponse,
    PirFindingCreate,
    PirFindingResponse,
    PirFindingUpdate,
)

router = APIRouter(prefix="/releases", tags=["pir"])


async def _hydrate(db: AsyncSession, tenant_id: int, pir):
    """One PIR with its findings, their actions and the incidents they cite,
    built once so every route returns the same shape. Batched: a fixed number of
    queries for the whole PIR, never one per finding."""
    if pir is None:
        return None
    now = datetime.now(timezone.utc)
    findings = await pir_finding_service.findings_for_pir(db, tenant_id, pir.id)
    actions = await pir_finding_service.actions_for_findings(
        db, tenant_id, [f.id for f in findings])
    names = await pir_finding_service.usernames_for(
        db, [a.owner_id for rows in actions.values() for a in rows])
    citations = await pir_finding_service.citations_for_findings(
        db, tenant_id, [f.id for f in findings])

    body = PIRResponse.model_validate(pir).model_dump()
    body["findings"] = []
    for finding in findings:
        item = PirFindingResponse.model_validate(finding).model_dump()
        item["actions"] = [
            {
                **PirActionResponse.model_validate(a).model_dump(
                    exclude={"owner_username", "is_overdue"}),
                "owner_username": names.get(a.owner_id),
                "is_overdue": pir_finding_service.is_overdue(a, now),
            }
            for a in actions[finding.id]
        ]
        item["incidents"] = citations[finding.id]
        body["findings"].append(item)
    return body


@router.get("/{release_id}/pir", response_model=PIRResponse | None)
async def get_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    return await _hydrate(db, tenant_id, await pir_service.get_for_release(db, tenant_id, release_id))


@router.post("/{release_id}/pir", response_model=PIRResponse, status_code=status.HTTP_201_CREATED)
async def create_pir(
    release_id: int,
    data: PIRCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    return await _hydrate(db, tenant_id, await pir_service.create_for_release(
        db, tenant_id, release_id, data, current_user.id))


@router.patch("/{release_id}/pir", response_model=PIRResponse)
async def update_pir(
    release_id: int,
    data: PIRUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    return await _hydrate(db, tenant_id, await pir_service.update(
        db, tenant_id, release_id, data))


@router.delete("/{release_id}/pir", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await pir_service.delete(db, current_user.active_tenant_id, release_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{release_id}/pir/findings", response_model=PirFindingResponse,
             status_code=status.HTTP_201_CREATED)
async def create_finding(
    release_id: int,
    data: PirFindingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await pir_finding_service.create_finding(db, tenant_id, pir, data, current_user.id)


@router.patch("/{release_id}/pir/findings/{finding_id}", response_model=PirFindingResponse)
async def update_finding(
    release_id: int,
    finding_id: int,
    data: PirFindingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    return await pir_finding_service.update_finding(db, tenant_id, finding_id, data)


@router.delete("/{release_id}/pir/findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finding(
    release_id: int,
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    await pir_finding_service.delete_finding(db, tenant_id, finding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{release_id}/pir/findings/{finding_id}/actions",
             response_model=PirActionResponse, status_code=status.HTTP_201_CREATED)
async def create_action(
    release_id: int,
    finding_id: int,
    data: PirActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    action = await pir_finding_service.create_action(db, tenant_id, finding, data, current_user.id)
    return await _action_response(db, action)


@router.patch("/{release_id}/pir/findings/{finding_id}/actions/{action_id}",
              response_model=PirActionResponse)
async def update_action(
    release_id: int,
    finding_id: int,
    action_id: int,
    data: PirActionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    await pir_finding_service.get_action_in_finding(db, tenant_id, finding, action_id)
    return await _action_response(
        db, await pir_finding_service.update_action(db, tenant_id, action_id, data))


@router.delete("/{release_id}/pir/findings/{finding_id}/actions/{action_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_action(
    release_id: int,
    finding_id: int,
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    await pir_finding_service.get_action_in_finding(db, tenant_id, finding, action_id)
    await pir_finding_service.delete_action(db, tenant_id, action_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{release_id}/pir/findings/{finding_id}/incidents",
             response_model=list[PirCitationResponse], status_code=status.HTTP_201_CREATED)
async def cite_incident(
    release_id: int,
    finding_id: int,
    data: PirCitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Cite an incident as evidence for a finding.

    Returns the finding's whole citation list, not just the new row: the caller
    is rendering a list, and re-citing an incident updates a row rather than
    adding one, so a single-row response would leave the page guessing which.
    """
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    await pir_finding_service.add_citation(db, tenant_id, finding, data.incident_id, data.note)
    return (await pir_finding_service.citations_for_findings(
        db, tenant_id, [finding_id]))[finding_id]


@router.delete("/{release_id}/pir/findings/{finding_id}/incidents/{incident_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def uncite_incident(
    release_id: int,
    finding_id: int,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.get_finding_in_pir(db, tenant_id, pir, finding_id)
    await pir_finding_service.remove_citation(db, tenant_id, finding_id, incident_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _action_response(db: AsyncSession, action) -> dict:
    """One action rendered the same way `_hydrate` renders it — one definition of
    the row shape, so a POST's response and a later GET's cannot disagree."""
    names = await pir_finding_service.usernames_for(db, [action.owner_id])
    return {
        **PirActionResponse.model_validate(action).model_dump(
            exclude={"owner_username", "is_overdue"}),
        "owner_username": names.get(action.owner_id),
        "is_overdue": pir_finding_service.is_overdue(action, datetime.now(timezone.utc)),
    }
