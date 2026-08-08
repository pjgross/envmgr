"""Insert a row, and lose gracefully if a concurrent writer got there first.

WHY THIS EXISTS. Both acknowledgement services read, branch, then write, with a
unique constraint behind them (`uq_conflict_ack_pair`, `uq_agreement_ack_booking`).
Two people acknowledging the same thing inside one transaction window both see
"no row", both INSERT, and one gets an IntegrityError — surfacing as a 500 on an
ordinary governance action that should simply have recorded the second answer.

WHY A SAVEPOINT, AND NOT JUST `try/except`. A failed flush leaves the SQLAlchemy
Session in a pending-rollback state on BOTH engines — every later statement
raises PendingRollbackError until something rolls back — and PostgreSQL
additionally poisons the transaction at the database level
(InFailedSqlTransaction). Either way the request is dead after the constraint
fires, even though the acknowledgement itself is recoverable, because `get_db`
commits the whole request at the end. Rolling back the SAVEPOINT rather than the
session undoes only the refused INSERT and leaves everything else usable.
(Measured, not assumed: removing `begin_nested` fails two of this module's tests
on SQLite AND on PostgreSQL. An earlier draft of this comment claimed SQLite was
unaffected — it is not.)

This is deliberately NOT `ON CONFLICT DO UPDATE`. That would be one round trip
instead of two, but the dialects spell it differently
(`postgresql.insert` vs `sqlite.insert`), and this codebase runs both engines in
CI precisely so that a dialect-specific path cannot pass unnoticed on one of
them. A savepoint is the same code on both.
"""
import logging
from typing import Awaitable, Callable, Optional, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def insert_or_reread(
    db: AsyncSession, row: T, reread: Callable[[], Awaitable[Optional[T]]]
) -> tuple[T, bool]:
    """Try to insert `row`. Return `(row, True)` if it landed.

    If a unique constraint refuses it, roll the savepoint back, call `reread`
    and return `(existing, False)` — the caller then applies its update to the
    row that won, so the later writer's answer is the one recorded, exactly as
    it would have been had the two calls not overlapped.

    `reread` must be the SAME tenant-scoped lookup the caller used before
    deciding to insert. Handing it a wider one would let a concurrent row from
    another tenant be adopted and updated.

    Re-raises if the row is still absent after the constraint refused the
    insert: that means the violation was some OTHER constraint, and swallowing
    it would turn a real schema error into a silent no-op.
    """
    nested = await db.begin_nested()
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Rolling the SAVEPOINT back — not the session — is what leaves the
        # surrounding transaction usable. It also detaches `row`, so no expunge
        # is needed and none is safe: it is already gone from the session.
        await nested.rollback()
        existing = await reread()
        if existing is None:
            raise
        logger.info(
            "insert_or_reread: lost an insert race on %s; updating the row that won",
            type(row).__name__,
        )
        return existing, False
    await nested.commit()
    return row, True
