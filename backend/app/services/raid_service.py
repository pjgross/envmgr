"""RAID service — scoring + status-transition helpers (pure) plus CRUD."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.raid import RaidItem, RaidItemHistory
from app.db.models.user import User
from app.db.models.release_dependency import ReleaseDependency
from app.api.v1.schemas.raid import RaidItemCreate, RaidItemUpdate, RaidItemRead
from app.services import release_service

# Allowed status transitions per item_type. `promoted` (risk) is a terminal
# state set only by the promotion action, not by ordinary transitions.
_TRANSITIONS: dict[str, dict[str, list[str]]] = {
    "risk": {
        "open": ["mitigating", "closed"],
        "mitigating": ["closed", "open"],
        "closed": [],
        "promoted": [],
    },
    "assumption": {
        "open": ["closed"],
        "closed": ["open"],
    },
    "issue": {
        "open": ["in_progress", "closed"],
        "in_progress": ["resolved", "open"],
        "resolved": ["closed", "in_progress"],
        "closed": [],
    },
    "dependency": {
        "identified": ["in_progress", "closed"],
        "in_progress": ["met", "closed"],
        "met": ["closed"],
        "closed": [],
    },
}


def severity(probability: Optional[int], impact: Optional[int]) -> Optional[int]:
    """probability x impact, or None if either factor is unset."""
    if probability is None or impact is None:
        return None
    return probability * impact


def rag(sev: Optional[int], config: dict) -> Optional[str]:
    """Map a severity score to a RAG band label using the tenant config bands."""
    if sev is None:
        return None
    for band in config.get("rag_bands", []):
        if band["min"] <= sev <= band["max"]:
            return band["rag"]
    return None


def is_transition_allowed(item_type: str, from_status: str, to_status: str) -> bool:
    """True if the status change is permitted for this item_type (same-state ok)."""
    if from_status == to_status:
        return True
    return to_status in _TRANSITIONS.get(item_type, {}).get(from_status, [])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_TYPE_PREFIX = {"risk": "R", "assumption": "A", "issue": "I", "dependency": "D"}
_INITIAL_STATUS = {"risk": "open", "assumption": "open", "issue": "open", "dependency": "identified"}


def ref_code(item: RaidItem) -> str:
    return f"{_TYPE_PREFIX[item.item_type]}-{item.seq:03d}"


def _jsonify(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _config_dict(config) -> dict:
    """Normalise a RaidConfig ORM object (or dict) into the dict `rag()` expects."""
    if config is None:
        return {}
    if isinstance(config, dict):
        return config
    return {
        "probability_scale": getattr(config, "probability_scale", None),
        "impact_scale": getattr(config, "impact_scale", None),
        "rag_bands": getattr(config, "rag_bands", []) or [],
    }


def to_read(item: RaidItem, config) -> RaidItemRead:
    cfg = _config_dict(config)
    read = RaidItemRead.model_validate(item)
    read.ref_code = ref_code(item)
    read.severity = severity(item.probability, item.impact)
    read.rag = rag(read.severity, cfg)
    return read


async def _validate_owner(db: AsyncSession, owner_id, tenant_id: int) -> None:
    if owner_id is None:
        return
    ok = (await db.execute(
        select(User.id).where(User.id == owner_id, User.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if ok is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "owner_id must be a user in this tenant")


async def _validate_release_dependency(db: AsyncSession, dep_id, tenant_id: int) -> None:
    if dep_id is None:
        return
    ok = (await db.execute(
        select(ReleaseDependency.id).where(ReleaseDependency.id == dep_id, ReleaseDependency.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if ok is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "release_dependency_id must belong to this tenant")


def _record_history(db, item, field_name, old, new, user_id):
    db.add(RaidItemHistory(
        tenant_id=item.tenant_id, raid_item_id=item.id, field_name=field_name,
        old_value={"v": _jsonify(old)}, new_value={"v": _jsonify(new)},
        changed_by=user_id or None, changed_at=datetime.now(timezone.utc),
    ))


async def _get_item(db: AsyncSession, item_id: int, tenant_id: int) -> RaidItem:
    item = (await db.execute(
        select(RaidItem).where(
            RaidItem.id == item_id, RaidItem.tenant_id == tenant_id, RaidItem.deleted_at.is_(None))
    )).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RAID item not found")
    return item


async def create_item(db: AsyncSession, release_id: int, data: RaidItemCreate,
                      tenant_id: int, user_id: int) -> RaidItem:
    await release_service.get_release(db, release_id, tenant_id)  # 404 if not in tenant
    await _validate_owner(db, data.owner_id, tenant_id)
    await _validate_release_dependency(db, data.release_dependency_id, tenant_id)
    max_seq = (await db.execute(
        select(func.max(RaidItem.seq)).where(
            RaidItem.tenant_id == tenant_id, RaidItem.release_id == release_id,
            RaidItem.item_type == data.item_type)
    )).scalar()
    now = datetime.now(timezone.utc)
    item = RaidItem(
        tenant_id=tenant_id, release_id=release_id, item_type=data.item_type,
        seq=(max_seq or 0) + 1, title=data.title, description=data.description,
        status=_INITIAL_STATUS[data.item_type], owner_id=data.owner_id,
        raised_by=user_id, raised_at=now, target_date=data.target_date, review_date=data.review_date,
        probability=data.probability, impact=data.impact,
        response_strategy=data.response_strategy, mitigation_plan=data.mitigation_plan,
        contingency_plan=data.contingency_plan,
        validation_status="unvalidated" if data.item_type == "assumption" else None,
        evidence=data.evidence, resolution_plan=data.resolution_plan,
        direction=data.direction, counterparty=data.counterparty, due_date=data.due_date,
        release_dependency_id=data.release_dependency_id, custom_fields=data.custom_fields,
    )
    db.add(item)
    await db.flush()
    _record_history(db, item, "created", None, item.status, user_id)
    await db.flush()
    return item


async def list_items(db: AsyncSession, release_id: int, tenant_id: int, *,
                     item_type=None, status=None, owner_id=None, rag=None, overdue=None, config=None):
    stmt = select(RaidItem).where(
        RaidItem.tenant_id == tenant_id, RaidItem.release_id == release_id,
        RaidItem.deleted_at.is_(None))
    if item_type:
        stmt = stmt.where(RaidItem.item_type == item_type)
    if status:
        stmt = stmt.where(RaidItem.status == status)
    if owner_id:
        stmt = stmt.where(RaidItem.owner_id == owner_id)
    stmt = stmt.order_by(RaidItem.item_type, RaidItem.seq)
    items = list((await db.execute(stmt)).scalars().all())
    if rag is not None and config is not None:
        cfg = _config_dict(config)
        items = [i for i in items if globals()["rag"](severity(i.probability, i.impact), cfg) == rag]
    if overdue:
        now = datetime.now(timezone.utc)
        items = [i for i in items if i.review_date and i.review_date < now
                 and i.status not in ("closed", "promoted", "met")]
    return items


async def get_item(db: AsyncSession, item_id: int, tenant_id: int) -> RaidItem:
    return await _get_item(db, item_id, tenant_id)


async def update_item(db: AsyncSession, item_id: int, data: RaidItemUpdate,
                      tenant_id: int, user_id: int) -> RaidItem:
    item = await _get_item(db, item_id, tenant_id)
    update_data = data.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] != item.status:
        if not is_transition_allowed(item.item_type, item.status, update_data["status"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid status transition")
    if "owner_id" in update_data:
        await _validate_owner(db, update_data["owner_id"], tenant_id)
    now = datetime.now(timezone.utc)
    for field, new in update_data.items():
        old = getattr(item, field)
        if old == new:
            continue
        setattr(item, field, new)
        _record_history(db, item, field, old, new, user_id)
    # side-effect timestamps
    if item.status in ("closed",) and item.closed_at is None:
        item.closed_at = now
    if item.item_type == "issue" and item.status == "resolved" and item.resolved_at is None:
        item.resolved_at = now
    if item.item_type == "assumption" and item.validation_status == "validated" and item.validated_at is None:
        item.validated_at = now
    await db.flush()
    return item


async def delete_item(db: AsyncSession, item_id: int, tenant_id: int, user_id: int) -> None:
    item = await _get_item(db, item_id, tenant_id)
    item.deleted_at = datetime.now(timezone.utc)
    await db.flush()
