"""Pure computation of a release's scope-window status.

A release's scope window tells a release manager whether scope can still be
added before the cutoff (`scope_deadline`). Derived from data we already have
so no new columns or queries are required.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

# A window this close to (or past) its cutoff is flagged "closing_soon".
CLOSING_SOON_DAYS = 7


def compute_scope_window(
    scope_deadline: Optional[datetime],
    actual_date: Optional[datetime],
    now: datetime,
) -> tuple[str, Optional[int]]:
    """Return (window_status, days_to_cutoff).

    window_status is one of: shipped, no_cutoff, closed, closing_soon, open.
    days_to_cutoff is a signed day count (negative once past), or None when
    there is no meaningful cutoff (shipped / no_cutoff). Checked in order:

    1. actual_date set        -> shipped   (release deployed; scope closed)
    2. scope_deadline is None -> no_cutoff (nothing to measure against)
    3. now >= scope_deadline  -> closed
    4. within CLOSING_SOON    -> closing_soon
    5. otherwise              -> open
    """
    if actual_date is not None:
        return "shipped", None
    if scope_deadline is None:
        return "no_cutoff", None

    deadline = scope_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    days = (deadline - now).days
    if now >= deadline:
        return "closed", days
    if deadline - now <= timedelta(days=CLOSING_SOON_DAYS):
        return "closing_soon", days
    return "open", days
