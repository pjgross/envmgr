# Received Conflict Feedback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Feedback received" tab alongside the existing editable conflicts list on the booking detail page, showing feedback that owners of conflicting bookings have posted about this booking.

**Architecture:** New backend endpoint `GET /bookings/{id}/received-feedback` returns `BookingConflictAck` rows where `other_booking_id == id`, joined with the source booking, source booking request, and the two user records (acknowledger + booked_by). Frontend `ConflictsPanel` is restructured into two MUI tabs sharing one outer `<Paper>`; the second tab renders a new read-only `ReceivedFeedbackList` component. Both fetches happen in parallel on mount and after mutations.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, pytest + aiosqlite, React 18, MUI v5, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-04-18-received-conflict-feedback-design.md`

---

## File Structure

**Backend**
- `backend/app/api/v1/schemas/conflict.py` — add `UserRef`, `RequestContextRef`, `ReceivedFeedbackItem`.
- `backend/app/services/conflict_service.py` — add `list_received_feedback()`.
- `backend/app/api/v1/conflicts.py` — add `GET /bookings/{id}/received-feedback` handler.
- `backend/tests/test_conflict_service.py` — add service-layer tests.
- `backend/tests/test_conflicts_api.py` — add API-layer tests.

**Frontend**
- `frontend/src/types/conflict.ts` — add `UserRef`, `RequestContextRef`, `ReceivedFeedbackItem` types.
- `frontend/src/services/bookingService.ts` — add `getReceivedFeedback()`.
- `frontend/src/components/bookings/ReceivedFeedbackList.tsx` — new read-only list component.
- `frontend/src/components/bookings/ConflictsPanel.tsx` — add tabs, parallel fetch, reload helper.

---

### Task 1: Backend schemas — UserRef, RequestContextRef, ReceivedFeedbackItem

**Files:**
- Modify: `backend/app/api/v1/schemas/conflict.py`

- [ ] **Step 1: Add the three new schemas**

Open `backend/app/api/v1/schemas/conflict.py` and replace its contents with:

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.booking_request import EnvBookingSummary


class ConflictAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_by: Optional[int]
    acknowledged_at: Optional[datetime]


class ConflictItem(BaseModel):
    other_booking: EnvBookingSummary
    ack: Optional[ConflictAckRead] = None


class ConflictAckUpsert(BaseModel):
    willing_to_share: bool
    notes: Optional[str] = None


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str


class RequestContextRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_name: str
    notes: Optional[str] = None
    context_tag: str
    exclusive_use_requested: bool
    booked_by: UserRef


class ReceivedFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_at: datetime
    acknowledged_by: UserRef

    source_booking: EnvBookingSummary
    source_request: RequestContextRef
```

- [ ] **Step 2: Verify import sanity**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. python -c "from app.api.v1.schemas.conflict import ReceivedFeedbackItem, UserRef, RequestContextRef; print('ok')"`
Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add backend/app/api/v1/schemas/conflict.py
git commit -m "feat(conflicts): add schemas for received-feedback endpoint"
```

---

### Task 2: Service — failing tests for `list_received_feedback`

**Files:**
- Modify: `backend/tests/test_conflict_service.py`

- [ ] **Step 1: Add the new tests at the end of the file**

Append to `backend/tests/test_conflict_service.py`:

```python
from app.db.models.booking_conflict_ack import BookingConflictAck


async def _make_ack(
    db_session,
    *,
    tenant_id: int,
    booking_id: int,
    other_booking_id: int,
    user_id: int,
    willing_to_share: bool | None,
    notes: str | None,
    at: datetime,
) -> BookingConflictAck:
    ack = BookingConflictAck(
        tenant_id=tenant_id,
        booking_id=booking_id,
        other_booking_id=other_booking_id,
        willing_to_share=willing_to_share,
        notes=notes,
        acknowledged_by=user_id,
        acknowledged_at=at,
    )
    db_session.add(ack)
    await db_session.flush()
    return ack


@pytest.mark.asyncio
async def test_received_feedback_returns_acks_targeting_this_booking(
    db_session, test_tenant, test_user
):
    env = await _make_env(db_session, test_tenant)
    req_me = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req_me.id

    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    other_req = await _make_request_with_owner(db_session, test_tenant, test_user)
    other.booking_request_id = other_req.id
    await db_session.flush()

    await _make_ack(
        db_session,
        tenant_id=test_tenant.id,
        booking_id=other.id,
        other_booking_id=me.id,
        user_id=test_user.id,
        willing_to_share=True,
        notes="we can share wed onwards",
        at=datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
    )

    rows = await conflict_service.list_received_feedback(
        db_session, me.id, test_tenant.id
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.ack.willing_to_share is True
    assert row.ack.notes == "we can share wed onwards"
    assert row.source_booking.id == other.id
    assert row.source_request.id == other_req.id
    assert row.acknowledged_by.id == test_user.id
    assert row.booked_by.id == test_user.id


@pytest.mark.asyncio
async def test_received_feedback_excludes_empty_rows(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    req_me = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req_me.id

    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    other_req = await _make_request_with_owner(db_session, test_tenant, test_user)
    other.booking_request_id = other_req.id
    await db_session.flush()

    await _make_ack(
        db_session,
        tenant_id=test_tenant.id,
        booking_id=other.id,
        other_booking_id=me.id,
        user_id=test_user.id,
        willing_to_share=None,
        notes=None,
        at=datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
    )

    rows = await conflict_service.list_received_feedback(
        db_session, me.id, test_tenant.id
    )
    assert rows == []


@pytest.mark.asyncio
async def test_received_feedback_tenant_isolation(db_session, test_tenant, test_user):
    from app.db.models.user import Tenant

    other_tenant = Tenant(name="Other", slug="other")
    db_session.add(other_tenant)
    await db_session.flush()

    env = await _make_env(db_session, test_tenant)
    req_me = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req_me.id

    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    other_req = await _make_request_with_owner(db_session, test_tenant, test_user)
    other.booking_request_id = other_req.id
    await db_session.flush()

    await _make_ack(
        db_session,
        tenant_id=test_tenant.id,
        booking_id=other.id,
        other_booking_id=me.id,
        user_id=test_user.id,
        willing_to_share=True,
        notes="seen",
        at=datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
    )

    rows = await conflict_service.list_received_feedback(
        db_session, me.id, other_tenant.id
    )
    assert rows == []


@pytest.mark.asyncio
async def test_received_feedback_ordered_by_acknowledged_at_desc(
    db_session, test_tenant, test_user
):
    env = await _make_env(db_session, test_tenant)
    req_me = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req_me.id

    early = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    early_req = await _make_request_with_owner(db_session, test_tenant, test_user)
    early.booking_request_id = early_req.id

    late = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    late_req = await _make_request_with_owner(db_session, test_tenant, test_user)
    late.booking_request_id = late_req.id
    await db_session.flush()

    await _make_ack(
        db_session,
        tenant_id=test_tenant.id,
        booking_id=early.id,
        other_booking_id=me.id,
        user_id=test_user.id,
        willing_to_share=True,
        notes="first",
        at=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
    )
    await _make_ack(
        db_session,
        tenant_id=test_tenant.id,
        booking_id=late.id,
        other_booking_id=me.id,
        user_id=test_user.id,
        willing_to_share=False,
        notes="second",
        at=datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc),
    )

    rows = await conflict_service.list_received_feedback(
        db_session, me.id, test_tenant.id
    )
    assert [r.ack.notes for r in rows] == ["second", "first"]
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/backend
PYTHONPATH=. uv run pytest tests/test_conflict_service.py -k received_feedback -v
```
Expected: all four tests fail with `AttributeError: module 'app.services.conflict_service' has no attribute 'list_received_feedback'`.

---

### Task 3: Service — implement `list_received_feedback`

**Files:**
- Modify: `backend/app/services/conflict_service.py`

- [ ] **Step 1: Add two new imports at the top of the file**

In `backend/app/services/conflict_service.py`, after the existing imports, add:

```python
from dataclasses import dataclass
from sqlalchemy.orm import aliased
```

- [ ] **Step 2: Add the return-row dataclass and the service function**

Append at the end of `backend/app/services/conflict_service.py`:

```python
@dataclass
class ReceivedFeedbackRow:
    ack: BookingConflictAck
    source_booking: Booking
    source_request: BookingRequest
    acknowledged_by: User
    booked_by: User


async def list_received_feedback(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[ReceivedFeedbackRow]:
    """Return acks left by other bookings' owners about this booking.

    Excludes rows where both willing_to_share and notes are empty (no actual
    feedback posted yet). Ordered by acknowledged_at DESC.
    """
    AckUser = aliased(User)
    OwnerUser = aliased(User)

    stmt = (
        select(
            BookingConflictAck,
            Booking,
            BookingRequest,
            AckUser,
            OwnerUser,
        )
        .join(Booking, Booking.id == BookingConflictAck.booking_id)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .join(AckUser, AckUser.id == BookingConflictAck.acknowledged_by)
        .join(OwnerUser, OwnerUser.id == BookingRequest.booked_by)
        .where(
            BookingConflictAck.other_booking_id == booking_id,
            BookingConflictAck.tenant_id == tenant_id,
            or_(
                BookingConflictAck.willing_to_share.is_not(None),
                and_(
                    BookingConflictAck.notes.is_not(None),
                    BookingConflictAck.notes != "",
                ),
            ),
        )
        .order_by(BookingConflictAck.acknowledged_at.desc())
    )
    result = await db.execute(stmt)
    return [
        ReceivedFeedbackRow(
            ack=ack,
            source_booking=booking,
            source_request=req,
            acknowledged_by=ack_user,
            booked_by=owner_user,
        )
        for ack, booking, req, ack_user, owner_user in result.all()
    ]
```

- [ ] **Step 3: Run the service tests and confirm they pass**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/backend
PYTHONPATH=. uv run pytest tests/test_conflict_service.py -k received_feedback -v
```
Expected: all four new tests PASS, other tests still PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add backend/app/services/conflict_service.py backend/tests/test_conflict_service.py
git commit -m "feat(conflicts): list_received_feedback service + tests"
```

---

### Task 4: API — failing test for GET /received-feedback

**Files:**
- Modify: `backend/tests/test_conflicts_api.py`

- [ ] **Step 1: Add tests to the bottom of the file**

Append to `backend/tests/test_conflicts_api.py`:

```python
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_received_feedback_empty(client: AsyncClient, auth_headers: dict, test_booking):
    resp = await client.get(
        f"/api/v1/bookings/{test_booking.id}/received-feedback",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_received_feedback_returns_row_with_context(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
    test_tenant,
    test_user,
    test_booking,
    test_conflicting_booking,
):
    from app.db.models.booking_conflict_ack import BookingConflictAck

    ack = BookingConflictAck(
        tenant_id=test_tenant.id,
        booking_id=test_conflicting_booking.id,
        other_booking_id=test_booking.id,
        willing_to_share=True,
        notes="we can share later in the week",
        acknowledged_by=test_user.id,
        acknowledged_at=datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
    )
    db_session.add(ack)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/bookings/{test_booking.id}/received-feedback",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["willing_to_share"] is True
    assert row["notes"] == "we can share later in the week"
    assert row["acknowledged_by"]["username"] == test_user.username
    assert row["acknowledged_by"]["email"] == test_user.email
    assert row["source_booking"]["id"] == test_conflicting_booking.id
    assert row["source_request"]["project_name"] == "Conflicting Project"
    assert row["source_request"]["booked_by"]["id"] == test_user.id
```

- [ ] **Step 2: Run and confirm failure**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/backend
PYTHONPATH=. uv run pytest tests/test_conflicts_api.py -k received_feedback -v
```
Expected: both tests fail with HTTP 404 (route does not exist).

---

### Task 5: API — add the handler

**Files:**
- Modify: `backend/app/api/v1/conflicts.py`

- [ ] **Step 1: Add the handler**

Replace `backend/app/api/v1/conflicts.py` with:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import conflict_service
from app.api.v1.schemas.conflict import (
    ConflictAckUpsert,
    ConflictAckRead,
    ConflictItem,
    ReceivedFeedbackItem,
    UserRef,
    RequestContextRef,
)
from app.api.v1.schemas.booking_request import EnvBookingSummary

router = APIRouter(prefix="/bookings", tags=["conflicts"])


@router.get("/{booking_id}/conflicts", response_model=list[ConflictItem])
async def list_conflicts(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    others = await conflict_service.list_conflicts(
        db, booking_id, current_user.active_tenant_id
    )
    items: list[ConflictItem] = []
    for o in others:
        ack = await conflict_service.get_ack(db, booking_id, o.id, current_user.active_tenant_id)
        items.append(ConflictItem(
            other_booking=EnvBookingSummary(
                id=o.id, environment_id=o.environment_id,
                start_date=o.start_date, end_date=o.end_date, status=o.status,
            ),
            ack=ConflictAckRead.model_validate(ack) if ack else None,
        ))
    return items


@router.put("/{booking_id}/conflicts/{other_id}/ack", response_model=ConflictAckRead)
async def ack_conflict(
    booking_id: int,
    other_id: int,
    data: ConflictAckUpsert,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    ack = await conflict_service.upsert_ack(
        db, booking_id, other_id,
        willing_to_share=data.willing_to_share,
        notes=data.notes,
        current_user=current_user,
        tenant_id=current_user.active_tenant_id,
    )
    return ConflictAckRead.model_validate(ack)


@router.get(
    "/{booking_id}/received-feedback",
    response_model=list[ReceivedFeedbackItem],
)
async def list_received_feedback(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows = await conflict_service.list_received_feedback(
        db, booking_id, current_user.active_tenant_id
    )
    return [
        ReceivedFeedbackItem(
            willing_to_share=r.ack.willing_to_share,
            notes=r.ack.notes,
            acknowledged_at=r.ack.acknowledged_at,
            acknowledged_by=UserRef.model_validate(r.acknowledged_by),
            source_booking=EnvBookingSummary(
                id=r.source_booking.id,
                environment_id=r.source_booking.environment_id,
                start_date=r.source_booking.start_date,
                end_date=r.source_booking.end_date,
                status=r.source_booking.status,
            ),
            source_request=RequestContextRef(
                id=r.source_request.id,
                project_name=r.source_request.project_name,
                notes=r.source_request.notes,
                context_tag=r.source_request.context_tag,
                exclusive_use_requested=r.source_request.exclusive_use_requested,
                booked_by=UserRef.model_validate(r.booked_by),
            ),
        )
        for r in rows
    ]
```

- [ ] **Step 2: Run API tests and confirm pass**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/backend
PYTHONPATH=. uv run pytest tests/test_conflicts_api.py -v
```
Expected: all tests PASS (including the two new ones).

- [ ] **Step 3: Run the full conflicts test suite to confirm no regressions**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/backend
PYTHONPATH=. uv run pytest tests/test_conflicts_api.py tests/test_conflict_service.py -v
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add backend/app/api/v1/conflicts.py backend/tests/test_conflicts_api.py
git commit -m "feat(conflicts): GET /bookings/{id}/received-feedback endpoint"
```

---

### Task 6: Frontend — add `ReceivedFeedbackItem` types

**Files:**
- Modify: `frontend/src/types/conflict.ts`

- [ ] **Step 1: Replace file contents with:**

```typescript
import type { EnvBookingSummary } from './bookingRequest'

export type ConflictAck = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_by: number | null
  acknowledged_at: string | null
}

export type ConflictItem = {
  other_booking: EnvBookingSummary
  ack: ConflictAck | null
}

export type UserRef = {
  id: number
  username: string
  email: string
}

export type RequestContextRef = {
  id: number
  project_name: string
  notes: string | null
  context_tag: string
  exclusive_use_requested: boolean
  booked_by: UserRef
}

export type ReceivedFeedbackItem = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_at: string
  acknowledged_by: UserRef
  source_booking: EnvBookingSummary
  source_request: RequestContextRef
}
```

- [ ] **Step 2: Type check**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npx tsc --noEmit
```
Expected: no type errors.

---

### Task 7: Frontend — add `getReceivedFeedback` service method

**Files:**
- Modify: `frontend/src/services/bookingService.ts`

- [ ] **Step 1: Update the import and add the method**

At the top of `frontend/src/services/bookingService.ts`, find the existing import line for `conflict` types:

```typescript
import type { ConflictAck, ConflictItem } from '../types/conflict';
```

Replace with:

```typescript
import type { ConflictAck, ConflictItem, ReceivedFeedbackItem } from '../types/conflict';
```

Then inside the `bookingService` object, add the new method immediately after `acknowledgeConflict`:

```typescript
  getReceivedFeedback: (id: number): Promise<ReceivedFeedbackItem[]> =>
    api.get(`/bookings/${id}/received-feedback`).then((r) => r.data),
```

- [ ] **Step 2: Type check**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npx tsc --noEmit
```
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add frontend/src/types/conflict.ts frontend/src/services/bookingService.ts
git commit -m "feat(frontend): received-feedback types and service"
```

---

### Task 8: Frontend — new `ReceivedFeedbackList` component

**Files:**
- Create: `frontend/src/components/bookings/ReceivedFeedbackList.tsx`

- [ ] **Step 1: Create the file with this content:**

```typescript
import { Box, Link, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { ReceivedFeedbackItem } from '../../types/conflict'

type Props = {
  items: ReceivedFeedbackItem[]
}

function willingLabel(v: boolean | null): string {
  if (v === true) return 'Yes'
  if (v === false) return 'No'
  return '(not yet answered)'
}

export default function ReceivedFeedbackList({ items }: Props) {
  if (items.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No feedback received yet.
      </Typography>
    )
  }

  return (
    <Box>
      {items.map((it, idx) => (
        <Box
          key={`${it.source_booking.id}-${it.acknowledged_at}`}
          sx={{
            mb: 2,
            pb: 2,
            borderBottom: idx === items.length - 1 ? 'none' : '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography variant="body2">
            <Link component={RouterLink} to={`/bookings/${it.source_booking.id}`}>
              Booking #{it.source_booking.id}
            </Link>
            {' · '}
            {new Date(it.source_booking.start_date).toLocaleDateString()} –{' '}
            {new Date(it.source_booking.end_date).toLocaleDateString()}
            {' · status '}
            {it.source_booking.status}
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            Project: <strong>{it.source_request.project_name}</strong>
            {'  '}
            Booked by: {it.source_request.booked_by.username} ({it.source_request.booked_by.email})
          </Typography>
          <Typography variant="body2" sx={{ mt: 1 }}>
            Willing to share: <strong>{willingLabel(it.willing_to_share)}</strong>
          </Typography>
          {it.notes && (
            <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
              “{it.notes}”
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            — {it.acknowledged_by.username}, {new Date(it.acknowledged_at).toLocaleString()}
          </Typography>
        </Box>
      ))}
    </Box>
  )
}
```

- [ ] **Step 2: Type check**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npx tsc --noEmit
```
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add frontend/src/components/bookings/ReceivedFeedbackList.tsx
git commit -m "feat(frontend): ReceivedFeedbackList component"
```

---

### Task 9: Frontend — restructure `ConflictsPanel` with tabs

**Files:**
- Modify: `frontend/src/components/bookings/ConflictsPanel.tsx`

- [ ] **Step 1: Replace the full file contents with:**

```typescript
import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, FormControlLabel, Paper, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import { bookingService } from '../../services/bookingService'
import type { ConflictItem, ReceivedFeedbackItem } from '../../types/conflict'
import { formatApiError } from '../../services/apiError'
import ReceivedFeedbackList from './ReceivedFeedbackList'

type Props = {
  bookingId: number
  canAcknowledge: boolean
}

export default function ConflictsPanel({ bookingId, canAcknowledge }: Props) {
  const [tab, setTab] = useState(0)
  const [items, setItems] = useState<ConflictItem[]>([])
  const [received, setReceived] = useState<ReceivedFeedbackItem[]>([])
  const [pending, setPending] = useState<Record<number, { willing_to_share: boolean; notes: string }>>({})
  const [conflictsError, setConflictsError] = useState<string | null>(null)
  const [receivedError, setReceivedError] = useState<string | null>(null)

  const reload = async () => {
    const [conflictsRes, receivedRes] = await Promise.allSettled([
      bookingService.getConflicts(bookingId),
      bookingService.getReceivedFeedback(bookingId),
    ])
    if (conflictsRes.status === 'fulfilled') {
      setItems(conflictsRes.value)
      setConflictsError(null)
    } else {
      setConflictsError(formatApiError(conflictsRes.reason, 'Failed to load conflicts'))
    }
    if (receivedRes.status === 'fulfilled') {
      setReceived(receivedRes.value)
      setReceivedError(null)
    } else {
      setReceivedError(formatApiError(receivedRes.reason, 'Failed to load received feedback'))
    }
  }

  useEffect(() => { reload() }, [bookingId])

  if (items.length === 0 && received.length === 0) return null

  const saveAck = async (otherId: number) => {
    const p = pending[otherId] ?? { willing_to_share: false, notes: '' }
    await bookingService.acknowledgeConflict(bookingId, otherId, p)
    await reload()
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label={`Your feedback (${items.length})`} />
        <Tab label={`Feedback received (${received.length})`} />
      </Tabs>

      {tab === 0 && (
        <Box>
          {conflictsError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setConflictsError(null)}>
              {conflictsError}
            </Alert>
          )}
          {items.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No conflicts for this booking.
            </Typography>
          ) : (
            items.map((it) => {
              const p = pending[it.other_booking.id] ?? {
                willing_to_share: it.ack?.willing_to_share ?? false,
                notes: it.ack?.notes ?? '',
              }
              return (
                <Box key={it.other_booking.id} sx={{ mb: 2, pb: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="body2">
                    Booking #{it.other_booking.id} ({new Date(it.other_booking.start_date).toLocaleDateString()} – {new Date(it.other_booking.end_date).toLocaleDateString()}) — status {it.other_booking.status}
                  </Typography>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={p.willing_to_share}
                        disabled={!canAcknowledge}
                        onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, willing_to_share: e.target.checked } }))}
                      />
                    }
                    label="Willing to share"
                  />
                  <TextField
                    label="Notes" fullWidth size="small" multiline minRows={2}
                    value={p.notes}
                    disabled={!canAcknowledge}
                    onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, notes: e.target.value } }))}
                  />
                  {canAcknowledge && (
                    <Button sx={{ mt: 1 }} size="small" variant="contained" onClick={() => saveAck(it.other_booking.id)}>
                      Save
                    </Button>
                  )}
                  {it.ack?.acknowledged_at && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      Last updated {new Date(it.ack.acknowledged_at).toLocaleString()}
                    </Typography>
                  )}
                </Box>
              )
            })
          )}
        </Box>
      )}

      {tab === 1 && (
        <Box>
          {receivedError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setReceivedError(null)}>
              {receivedError}
            </Alert>
          )}
          <ReceivedFeedbackList items={received} />
        </Box>
      )}
    </Paper>
  )
}
```

Notes for the engineer:
- `Promise.allSettled` — so a failure loading one list doesn't clear the other.
- The outer panel returns `null` only when **both** lists are empty — matches the spec.
- `saveAck` still calls `reload()`, which refreshes both lists.

- [ ] **Step 2: Type check**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npx tsc --noEmit
```
Expected: no type errors.

- [ ] **Step 3: Build the frontend to catch lint/tsc regressions**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npm run build
```
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add frontend/src/components/bookings/ConflictsPanel.tsx
git commit -m "feat(frontend): tabs + received-feedback in ConflictsPanel"
```

---

### Task 10: Manual UI verification

**Files:** none — exploratory verification only.

- [ ] **Step 1: Start the dev stack**

In three terminals:

```bash
# 1. Infra
cd /Users/peter/Developer/Code/projects/envmgr && docker-compose up -d
```

```bash
# 2. Backend
cd /Users/peter/Developer/Code/projects/envmgr/backend && uvicorn app.main:app --reload
```

```bash
# 3. Frontend
cd /Users/peter/Developer/Code/projects/envmgr/frontend && npm run dev
```

- [ ] **Step 2: Seed two overlapping bookings in the demo tenant**

Log in as `admin` / `admin123` (tenant `demo`). Create two bookings on the same environment whose windows overlap. Note both booking IDs.

- [ ] **Step 3: Post feedback from each side**

- Open Booking A detail page. In the Conflicts panel ("Your feedback" tab) post feedback on Booking B (check "Willing to share", add a note, Save).
- Repeat on Booking B's detail page, posting feedback about Booking A.

- [ ] **Step 4: Verify each booking's "Feedback received" tab**

- On Booking A, switch to "Feedback received" — expect one row showing B's feedback, with B's project name, username, timestamp, the note, and willing-to-share value. Clicking `Booking #<B>` navigates to Booking B.
- On Booking B, "Feedback received" — expect one row showing A's feedback.

- [ ] **Step 5: Verify read-only + visibility rules**

- Log in as a non-owner, non-delegate user (seed or create one in the demo tenant). Visit Booking A — the "Your feedback" tab must show the conflicts list **without** save buttons (Checkbox and TextField disabled). The "Feedback received" tab must be visible and populated.
- Visit a booking with no conflicts and no received feedback — the `<Paper>` panel is not rendered at all.

- [ ] **Step 6: Verify error isolation**

- Temporarily stop the backend. Reload a booking detail page — each tab should show its own error alert, content-free, without blanking the other.
- Restart the backend; reload.

---

### Task 11: Playwright E2E smoke test (received-feedback tab renders)

**Files:**
- Modify: `frontend/e2e/bookings.spec.ts`

- [ ] **Step 1: Append a smoke test at the end of the file**

```typescript
test('Conflicts panel shows tabs when there is feedback', async ({ page }) => {
  // This test relies on seed data that includes two overlapping bookings and
  // a conflict ack between them. seed_e2e.py does not currently seed this,
  // so the test is skipped until seed data is extended.
  test.skip(true, 'requires seeded overlapping bookings + ack — extend seed_e2e.py first')

  await login(page)
  await page.goto('/bookings/list')
  await page.getByRole('link', { name: /booking #/i }).first().click()

  await expect(page.getByRole('tab', { name: /your feedback/i })).toBeVisible()
  await expect(page.getByRole('tab', { name: /feedback received/i })).toBeVisible()

  await page.getByRole('tab', { name: /feedback received/i }).click()
  await expect(page.getByText(/willing to share/i)).toBeVisible()
})
```

Notes for the engineer:
- `login` is defined at the top of the file; reuse it.
- The test is `skip`ped with a clear reason, matching the same pattern the existing file already uses for tests that need seeded data (see comment at line ~52). This ensures the CI suite stays green while leaving a visible breadcrumb for the next time seed data is extended.

- [ ] **Step 2: Run existing E2E suite to confirm nothing regressed**

Run:
```bash
cd /Users/peter/Developer/Code/projects/envmgr/frontend
npm run test:e2e -- bookings.spec.ts
```
Expected: existing tests PASS, new test SKIPPED with the documented reason.

- [ ] **Step 3: Commit**

```bash
cd /Users/peter/Developer/Code/projects/envmgr
git add frontend/e2e/bookings.spec.ts
git commit -m "test(e2e): skipped smoke test for received-feedback tab"
```

---

## Definition of Done

- Backend service + API tests green.
- `GET /bookings/{id}/received-feedback` returns acks targeting the booking, with source-booking and source-request context, tenant-scoped, ordered newest first, empty rows suppressed.
- Frontend `ConflictsPanel` renders two tabs; Tab 2 shows the new read-only list populated from the new endpoint.
- Outer panel hides only when both lists are empty.
- Edit controls in Tab 1 remain gated by `canAcknowledge`; Tab 2 has no edit affordances for any user.
- Manual verification steps in Task 10 all pass.
- Frontend `npm run build` succeeds; backend full conflict test suite green.
