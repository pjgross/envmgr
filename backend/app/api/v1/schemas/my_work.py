"""`/my-work` — one response, five "waiting on me" queues.

Every field here is rendered, never a bare id: `WorkItem.title` is a NAME
(environment, release, incident — see the display-names rule in CLAUDE.md),
because a personal inbox of things the reader has never seen is exactly where
a `#42` fallback is least readable.

`QueueResult.failed` is NOT the same as an empty queue (§5 — see
`my_work_service.build`'s per-queue try/except). A dashboard that goes blank
because one worklist query is unhappy is worse than one showing four of five
and saying so; the frontend renders `failed` and an empty `count`/`items`
differently for exactly that reason.
"""
from datetime import datetime

from pydantic import BaseModel


class WorkItem(BaseModel):
    id: int
    title: str            # a NAME, never "#42" — see the display-names rule
    subtitle: str | None = None
    url: str               # the detail route this row opens
    due: datetime | None = None


class QueueResult(BaseModel):
    count: int
    items: list[WorkItem]
    overdue: int | None = None   # pir_actions only
    failed: bool = False         # true => the queue could not be computed


class MyWorkResponse(BaseModel):
    as_of: datetime
    queues: dict[str, QueueResult]   # keys: environment_requests, contentions,
                                      # decommissions, pir_actions, incidents
