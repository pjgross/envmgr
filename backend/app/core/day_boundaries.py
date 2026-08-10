"""The one place that decides A DEADLINE IS A DAY, NOT AN INSTANT.

Extracted from `contention_service` when B2 needed the same rule for its grace
period and importing it there would have closed an import cycle:

    environment_service → environment_compliance_service
                        → contention_service → environment_service

The reasoning lives in the function's docstring, moved across verbatim with the
function. DO NOT ADD A SECOND COPY OF THIS RULE — A4 wrote that docstring
because applying the rule inconsistently, in two places that looked equivalent,
is exactly what produced the bug it describes.

`contention_service` still re-exports `expiry_boundary`, so its existing callers
and tests are unaffected by the move.
"""
from datetime import datetime, timezone
from typing import Optional


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes where PostgreSQL hands back aware ones,
    so normalise before any Python-side arithmetic — the stored values are UTC
    on both engines.

    A copy of `contention_service._utc`, which is itself one of five in this
    codebase (agreement_gap_service, environment_health_service,
    environment_utilization_service and release_metrics_service carry the
    others). Copied rather than imported for the reason recorded there: reaching
    into another module's private helper couples two files that share nothing
    else. The rule that must NOT be copied is the day boundary below.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def expiry_boundary(now: datetime) -> datetime:
    """The instant a deadline becomes late: the START OF THE UTC DAY `now` is in.

    A DEADLINE IS A DAY, NOT AN INSTANT, and this is the one place that decides
    so. `respond_by` is written by a `<input type="date">` through
    `toIsoDatetime`, which yields `"YYYY-MM-DDT00:00:00Z"` — so comparing it
    against `now` at instant precision made an escalation read `expired` from
    one minute past midnight on the very day it was due. The owner opening the
    worklist at 09:00 saw "decide by 10/08/2026" beside an **Expired** chip,
    having been given none of the day the product promised them; and because
    `state_predicate` compares the same way, `?state=open` EXCLUDED every
    contention due today — the queue hiding exactly the rows closest to their
    deadline.

    CALENDAR DAYS, COMPARED CONSISTENTLY — the rule this repo already paid for
    once. `expiryDayDelta`/`isExpiryOverdue` (frontend/src/utils/dates.ts) exist
    because `formatExpiry` reported an environment "overdue by 1 day" throughout
    the day it actually expired, for the same reason: a floored instant delta
    against a value stored at midnight. See CLAUDE.md's pitfall on day
    arithmetic.

    Both `escalation_state` and `state_predicate` call this, so the computed
    state and its SQL filter cannot drift apart — the "two mechanisms enforcing
    one outcome" shape that has repeatedly cost this branch. B2's
    `quarantine_clause` is the third caller, for the same reason: an environment
    created at 15:00 must not lose most of its last grace day, and the filter
    must not hide the rows closest to their deadline. Portable: it returns a
    plain instant, so the predicate needs no dialect date functions.

    Normalised through `astimezone(timezone.utc)`, not `replace(...)` alone: a
    caller holding an aware clock in another offset would otherwise get midnight
    in THAT offset, which is a different day.
    """
    return _utc(now).astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
