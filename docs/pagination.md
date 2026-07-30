# Pagination

Most list endpoints returned every matching row for the tenant. That is fine at demo scale and
a problem at real scale: a tenant with 50k bookings gets one query that loads 50k ORM objects,
serialises them all, and hands the browser a response it renders into a DataGrid. Nothing in
the stack said no.

## The primitive

[`app/core/pagination.py`](../backend/app/core/pagination.py):

```python
@router.get("/", response_model=list[EnvironmentResponse])
async def list_environments(
    response: Response,
    page: Page = Depends(pagination),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await environment_service.list_environments(
        db, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return rows
```

Services take `page: Optional[Page] = None` and end with `return await fetch_page(db, query, page)`,
returning `(rows, total)`. Passing `page=None` returns everything, so non-request callers keep
their old behaviour.

**Deliberately backward compatible.** Endpoints still return a bare JSON array — no client
change was needed — and the unwindowed total goes in `X-Total-Count`. A client that ignores the
header behaves exactly as before up to the cap; one that reads it can tell there is more and
walk it with `?offset=`.

`limit` defaults to 500 and is capped at 1000: generous enough that no realistic current page
truncates, low enough that one pathological tenant cannot take the API down with a single
request. Asking for more than the cap is a 422, not a silent clamp.

The total is counted with a separate query against the same filters rather than a window
function, so it stays correct for queries with joins or `DISTINCT` where a window count would
double-count.

## Bounded so far

| Endpoint | Service |
|---|---|
| `GET /environments/` | `environment_service.list_environments` |
| `GET /systems/` | `system_service.list_systems` |
| `GET /incidents` | `incident_service.list_incidents` |

## Not yet bounded

44 list endpoints still return everything. They fall into three groups.

**Growth-bearing — should be bounded next**, in rough order of how fast they grow:
`bookings`, `change_requests`, `booking_requests`, `releases` (11 endpoints: the release list
plus phases, gates, scope, systems, dependencies, changes, events), `deployments`,
`conflicts`, `dependencies`, `infrastructure_components`, `enterprise_rollup`,
`enterprise_memberships`, `tenant_admin` users, `admin` tenants, `environment_health`.

**Bounded in practice by tenant configuration**, where a cap would add a knob for no benefit:
`component_types`, `release_event_types`, `release_templates`, `tenant_admin_fields`,
`booking_lifecycle`, `api_keys`.

**Blocked on a refactor:** `GET /{release_id}/raid`. `raid_service.list_items` applies its
`rag` and `overdue` filters *in Python, after the query* — computed from probability/impact
against tenant config, and from review dates. A SQL `LIMIT` would window the pre-filter set and
then filter within that page, so `?limit=50` could return 3 rows while hundreds matched.
Bounding it means moving those two filters into SQL first; adding `limit` before that would be
worse than leaving it unbounded, because the results would be quietly wrong rather than merely
large.
