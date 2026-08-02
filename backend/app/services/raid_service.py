"""RAID service — scoring + status-transition helpers (pure) plus CRUD."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, false, not_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, fetch_page
from app.db.models.raid import RaidItem, RaidItemHistory, RaidItemScopeLink, RaidItemRelation
from app.db.models.user import User
from app.db.models.release_dependency import ReleaseDependency
from app.db.models.release_change import ReleaseChange
from app.api.v1.schemas.raid import RaidItemCreate, RaidItemUpdate, RaidItemRead
from app.services import release_service
from app.core.events import publish_event

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


def to_read(item: RaidItem, config, owner_username: Optional[str] = None) -> RaidItemRead:
    cfg = _config_dict(config)
    read = RaidItemRead.model_validate(item)
    read.ref_code = ref_code(item)
    read.severity = severity(item.probability, item.impact)
    read.rag = rag(read.severity, cfg)
    read.owner_username = owner_username
    return read


async def owner_usernames(
    db: AsyncSession, items: list[RaidItem], tenant_id: int
) -> dict[int, str]:
    """Usernames for the owners of `items`, in one query.

    The owner name used to be resolved in the browser against the shared
    tenant-users collection, which is capped server-side — so past the cap an
    item's owner rendered as an em dash, losing information rather than merely
    hiding an option. Sending the name with the row removes the dependency on
    that collection entirely, the same way ReleaseSystemRead carries
    `system_name`.
    """
    owner_ids = {i.owner_id for i in items if i.owner_id is not None}
    if not owner_ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.username).where(
            User.id.in_(owner_ids), User.tenant_id == tenant_id
        )
    )).all()
    return {uid: username for uid, username in rows}


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
    await publish_event(
        db, event_type="RaidItemRaised", aggregate_id=item.id, aggregate_type="RaidItem",
        payload={"item_type": item.item_type, "ref_code": ref_code(item), "release_id": item.release_id},
        tenant_id=tenant_id)
    return item


_PROMOTABLE = {("risk", "issue"), ("assumption", "risk"), ("assumption", "issue")}


async def promote_item(db, release_id: int, item_id: int, target_type: str,
                       tenant_id: int, user_id: int) -> RaidItem:
    source = await _get_item(db, item_id, tenant_id)
    if source.release_id != release_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RAID item not found")
    if (source.item_type, target_type) not in _PROMOTABLE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"cannot promote a {source.item_type} to a {target_type}")
    max_seq = (await db.execute(
        select(func.max(RaidItem.seq)).where(
            RaidItem.tenant_id == tenant_id, RaidItem.release_id == source.release_id,
            RaidItem.item_type == target_type)
    )).scalar()
    now = datetime.now(timezone.utc)
    new = RaidItem(
        tenant_id=tenant_id, release_id=source.release_id, item_type=target_type,
        seq=(max_seq or 0) + 1, title=source.title, description=source.description,
        status=_INITIAL_STATUS[target_type], owner_id=source.owner_id,
        raised_by=user_id, raised_at=now,
        probability=source.probability if target_type in ("risk", "issue") else None,
        impact=source.impact if target_type in ("risk", "issue") else None,
        validation_status="unvalidated" if target_type == "assumption" else None,
        promoted_from_id=source.id,
    )
    db.add(new)
    await db.flush()
    _record_history(db, new, "created", None, f"promoted from {ref_code(source)}", user_id)
    if source.item_type == "risk":
        prev = source.status
        source.status = "promoted"
        _record_history(db, source, "status", prev, "promoted", user_id)
    await db.flush()
    await publish_event(
        db, event_type="RaidItemPromoted", aggregate_id=source.id, aggregate_type="RaidItem",
        payload={"source_id": source.id, "new_id": new.id, "target_type": target_type},
        tenant_id=tenant_id)
    return new


def _rag_sql_condition(cfg: dict, wanted: str):
    """SQL predicate selecting items whose RAG band is `wanted`.

    rag() resolves by FIRST match, so a band only claims a severity no earlier
    band claimed. That exclusion is expressed directly rather than by
    enumerating a severity domain: probability and impact carry no upper
    validation and rag_bands is unvalidated, so any enumeration has a ceiling
    that can silently drop items above it.
    """
    severity_expr = RaidItem.probability * RaidItem.impact
    earlier = []
    matches = []
    for band in cfg.get("rag_bands", []) or []:
        in_band = severity_expr.between(band["min"], band["max"])
        if band.get("rag") == wanted:
            cond = in_band
            for prev in earlier:
                cond = and_(cond, not_(prev))
            matches.append(cond)
        earlier.append(in_band)
    return or_(*matches) if matches else false()


async def list_items(db: AsyncSession, release_id: int, tenant_id: int, *,
                     item_type=None, status=None, owner_id=None, rag=None,
                     overdue=None, config=None,
                     page: Optional[Page] = None) -> tuple[list[RaidItem], int]:
    """RAID items for a release, optionally filtered by type/status/owner/rag/overdue.

    `rag` and `overdue` are both pushed into SQL (see `_rag_sql_condition` and
    the review_date/status predicate below) rather than filtered in Python
    after the query, so the result can be windowed by `page`.
    """
    stmt = select(RaidItem).where(
        RaidItem.tenant_id == tenant_id, RaidItem.release_id == release_id,
        RaidItem.deleted_at.is_(None))
    if item_type:
        stmt = stmt.where(RaidItem.item_type == item_type)
    if status:
        stmt = stmt.where(RaidItem.status == status)
    if owner_id:
        stmt = stmt.where(RaidItem.owner_id == owner_id)
    if rag is not None and config is not None:
        # severity is probability * impact; NULL in either factor propagates
        # through BETWEEN/AND/OR, so unset items are excluded exactly as
        # severity()->None->rag()->None did.
        stmt = stmt.where(_rag_sql_condition(_config_dict(config), rag))
    if overdue:
        stmt = stmt.where(
            RaidItem.review_date.isnot(None),
            RaidItem.review_date < datetime.now(timezone.utc),
            RaidItem.status.notin_(("closed", "promoted", "met")),
        )
    stmt = stmt.order_by(RaidItem.item_type, RaidItem.seq, RaidItem.id)
    return await fetch_page(db, stmt, page)


async def summary(db, release_id: int, tenant_id: int, config) -> dict:
    cfg = _config_dict(config)
    items, _ = await list_items(db, release_id, tenant_id, config=cfg)
    psize = len(cfg.get("probability_scale", []))
    isize = len(cfg.get("impact_scale", []))
    heatmap = [[[] for _ in range(isize)] for _ in range(psize)]
    counts_by_type = {"risk": 0, "assumption": 0, "issue": 0, "dependency": 0}
    counts_by_rag = {"green": 0, "amber": 0, "red": 0}
    open_issues = 0
    overdue_reviews = 0
    now = datetime.now(timezone.utc)
    for it in items:
        counts_by_type[it.item_type] = counts_by_type.get(it.item_type, 0) + 1
        r = rag(severity(it.probability, it.impact), cfg)
        if r in counts_by_rag:
            counts_by_rag[r] += 1
        if it.item_type == "issue" and it.status != "closed":
            open_issues += 1
        if it.review_date and it.review_date < now and it.status not in ("closed", "promoted", "met"):
            overdue_reviews += 1
        if (it.item_type in ("risk", "issue") and it.probability and it.impact
                and 1 <= it.probability <= psize and 1 <= it.impact <= isize):
            heatmap[it.probability - 1][it.impact - 1].append(ref_code(it))
    return {
        "counts_by_type": counts_by_type,
        "counts_by_rag": counts_by_rag,
        "open_issues": open_issues,
        "overdue_reviews": overdue_reviews,
        "heatmap": heatmap,
    }


async def get_item(db: AsyncSession, item_id: int, tenant_id: int) -> RaidItem:
    return await _get_item(db, item_id, tenant_id)


async def update_item(db: AsyncSession, item_id: int, data: RaidItemUpdate,
                      tenant_id: int, user_id: int) -> RaidItem:
    item = await _get_item(db, item_id, tenant_id)
    _orig_status = item.status
    _orig_owner = item.owner_id
    update_data = data.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] != item.status:
        if not is_transition_allowed(item.item_type, item.status, update_data["status"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid status transition")
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
    if item.status != _orig_status:
        await publish_event(
            db, event_type="RaidItemStatusChanged", aggregate_id=item.id, aggregate_type="RaidItem",
            payload={"from": _orig_status, "to": item.status}, tenant_id=tenant_id)
        if item.status == "closed":
            await publish_event(
                db, event_type="RaidItemClosed", aggregate_id=item.id, aggregate_type="RaidItem",
                payload={"ref_code": ref_code(item)}, tenant_id=tenant_id)
    if item.owner_id != _orig_owner:
        await publish_event(
            db, event_type="RaidItemAssigned", aggregate_id=item.id, aggregate_type="RaidItem",
            payload={"owner_id": item.owner_id}, tenant_id=tenant_id)
    await db.flush()
    return item


async def delete_item(db: AsyncSession, item_id: int, tenant_id: int, user_id: int) -> None:
    item = await _get_item(db, item_id, tenant_id)
    item.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# ---------------------------------------------------------------------------
# Scope links + item relations
# ---------------------------------------------------------------------------

_RELATION_KINDS = ("relates_to", "caused_by", "duplicates", "blocks")


async def add_scope_link(db, release_id: int, item_id: int, release_change_id: int, tenant_id: int):
    item = await _get_item(db, item_id, tenant_id)
    if item.release_id != release_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RAID item not found")
    rc = (await db.execute(select(ReleaseChange).where(
        ReleaseChange.id == release_change_id, ReleaseChange.tenant_id == tenant_id,
        ReleaseChange.deleted_at.is_(None)))).scalar_one_or_none()
    if rc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "release_change_id must be a scope item in this tenant")
    if rc.release_id != release_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope item belongs to a different release")
    existing = (await db.execute(select(RaidItemScopeLink).where(
        RaidItemScopeLink.raid_item_id == item_id,
        RaidItemScopeLink.release_change_id == release_change_id))).scalar_one_or_none()
    if existing:
        return existing
    link = RaidItemScopeLink(tenant_id=tenant_id, raid_item_id=item_id, release_change_id=release_change_id)
    db.add(link)
    await db.flush()
    await publish_event(
        db, event_type="RaidItemLinkedToScope", aggregate_id=item_id, aggregate_type="RaidItem",
        payload={"release_change_id": release_change_id}, tenant_id=tenant_id)
    return link


async def remove_scope_link(db, item_id: int, release_change_id: int, tenant_id: int) -> None:
    await _get_item(db, item_id, tenant_id)
    link = (await db.execute(select(RaidItemScopeLink).where(
        RaidItemScopeLink.raid_item_id == item_id,
        RaidItemScopeLink.release_change_id == release_change_id,
        RaidItemScopeLink.tenant_id == tenant_id))).scalar_one_or_none()
    if link:
        await db.delete(link)
        await db.flush()


async def add_relation(db, from_item_id: int, to_item_id: int, relation: str, tenant_id: int):
    if relation not in _RELATION_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid relation")
    if from_item_id == to_item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot relate an item to itself")
    await _get_item(db, from_item_id, tenant_id)
    await _get_item(db, to_item_id, tenant_id)  # 404 if target not in tenant
    existing = (await db.execute(select(RaidItemRelation).where(
        RaidItemRelation.from_item_id == from_item_id,
        RaidItemRelation.to_item_id == to_item_id,
        RaidItemRelation.relation == relation))).scalar_one_or_none()
    if existing:
        return existing
    rel = RaidItemRelation(tenant_id=tenant_id, from_item_id=from_item_id, to_item_id=to_item_id, relation=relation)
    db.add(rel)
    await db.flush()
    return rel


async def remove_relation(db, from_item_id: int, to_item_id: int, relation: str, tenant_id: int) -> None:
    await _get_item(db, from_item_id, tenant_id)
    rel = (await db.execute(select(RaidItemRelation).where(
        RaidItemRelation.from_item_id == from_item_id,
        RaidItemRelation.to_item_id == to_item_id,
        RaidItemRelation.relation == relation,
        RaidItemRelation.tenant_id == tenant_id))).scalar_one_or_none()
    if rel:
        await db.delete(rel)
        await db.flush()


async def get_links(db, item_id: int, tenant_id: int) -> dict:
    await _get_item(db, item_id, tenant_id)
    scope_ids = [r[0] for r in (await db.execute(select(RaidItemScopeLink.release_change_id).where(
        RaidItemScopeLink.raid_item_id == item_id, RaidItemScopeLink.tenant_id == tenant_id))).all()]
    rels = [{"to_item_id": r.to_item_id, "relation": r.relation} for r in (await db.execute(
        select(RaidItemRelation).where(
            RaidItemRelation.from_item_id == item_id, RaidItemRelation.tenant_id == tenant_id))).scalars().all()]
    return {"scope_change_ids": scope_ids, "relations": rels}
