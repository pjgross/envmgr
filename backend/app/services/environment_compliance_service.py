"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.
"""
import asyncio
import re
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import String, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy

# Mirrors CustomFieldDefinition's own validation
# (app/api/v1/schemas/custom_field.py: FIELD_KEY_RE). Every field_key that can
# reach this function has already passed that regex — this is a second,
# independent check on the same charset, not a wider allowance.
_SAFE_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def custom_field_missing_clause(field_key: str) -> ColumnElement[bool]:
    """True when `custom_fields` does not supply a usable value for `field_key`.

    Absent, JSON null, and whitespace-only all count as missing; `0` and `false`
    do not — a `number` custom field storing zero is a supplied value, and
    `trim()` over the text form of `0` is `'0'`, which is non-empty.

    `Environment.custom_fields[field_key]` is dialect-compiled by SQLAlchemy:
    `->>` on PostgreSQL, `json_extract` on SQLite. `field_key` is a bound
    parameter, never interpolated — there is no SQL injection here. But on
    SQLite, SQLAlchemy's JSON comparator builds the `json_extract` path by raw
    string concatenation (`$."` + key + `"`), so a key containing `"` compiles
    to a malformed path: SQLite then reports the field missing while
    PostgreSQL, which has no such concatenation step, reports it present. The
    two engines silently disagree. Guard the charset here so that divergence
    is impossible rather than merely unreached — today's only caller already
    validates field_key against this same pattern, so this should never fire;
    if it does, someone has widened that charset without checking this
    consequence.
    """
    if not _SAFE_FIELD_KEY_RE.match(field_key):
        raise ValueError(
            f"field_key {field_key!r} contains characters outside "
            f"{_SAFE_FIELD_KEY_RE.pattern!r} — SQLite's JSON path comparator "
            "builds its path by raw string concatenation, so a key with a "
            'double-quote (or other unsafe character) compiles to a '
            "malformed path on SQLite while PostgreSQL resolves it fine, "
            "making the two engines disagree about whether the field is "
            "missing."
        )
    value = Environment.custom_fields[field_key].as_string()
    return or_(
        value.is_(None),
        func.trim(func.cast(value, String)) == "",
    )


MAX_PATTERN_LENGTH = 500
# environment.name is String(200), so a probe that ran the full 200 characters
# would be the closest analogue to a real worst-case name. Deliberately NOT
# used: a probe is only useful if it terminates. The trailing "!" (a STRING
# THAT FAILS TO MATCH) is what forces a catastrophic pattern like `(a+)+$` to
# exhaust every partition of its nested quantifier before giving up — a run
# of plain "a"s with nothing to break the match resolves on the engine's
# first (greedy) attempt, in microseconds, with no backtracking at all. Once
# that mismatch is present, cost is exponential in length: confirmed by hand,
# fullmatch("(a+)+$", "a"*27 + "!") already takes ~2.5s. `asyncio.wait_for`
# abandons rather than kills the worker thread (see `validate_pattern_async`),
# and that thread is not merely slow to finish — for a genuinely catastrophic
# pattern at length 200 it would not finish in any practical amount of time,
# pinning a thread pool worker forever. 27 is chosen to keep the abandoned
# thread's own eventual completion in the low single-digit seconds — long
# enough to demonstrate the guard with comfortable margin over
# _PROBE_TIMEOUT_SECONDS, short enough that an abandoned probe thread doesn't
# make this process (or, worse, a production worker) unkillable in practice.
_PROBE_STRING = "a" * 27 + "!"
_PROBE_TIMEOUT_SECONDS = 0.25


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def name_matches(pattern: str, name: str) -> bool:
    """THE one regex call site in this application.

    `fullmatch`, not `search`: a pattern anchors by default, because a tenant
    writing `dev-.*` and having `xxdev-1` accepted is the likelier error.
    """
    return _compiled(pattern).fullmatch(name or "") is not None


def _pattern_in_force(policy: Optional[EnvironmentNamingPolicy]) -> Optional[str]:
    if policy is None or not policy.is_enabled or not policy.name_pattern:
        return None
    return policy.name_pattern


def evaluate_name(
    policy: Optional[EnvironmentNamingPolicy], name: str
) -> Optional[bool]:
    """The verdict stored on `environment.name_compliant`.

    None means NO PATTERN APPLIES — not unknown, not failing.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None:
        return None
    return name_matches(pattern, name)


def assert_name_allowed(
    policy: Optional[EnvironmentNamingPolicy],
    submitted: str,
    stored: Optional[str],
) -> None:
    """The ONLY refusal in the whole of B2, and only for a CHANGED name.

    A full-form save re-sending an existing bad name is accepted — otherwise
    activating a policy freezes every non-conforming environment's next save,
    the same shape as A1's archived-FK-value carve-out.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None or submitted == stored:
        return
    if name_matches(pattern, submitted):
        return
    example = policy.name_pattern_example
    hint = f" For example: '{example}'." if example else ""
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"'{submitted}' does not match this tenant's environment naming "
        f"convention ({pattern}).{hint}",
    )


def validate_pattern(pattern: Optional[str], example: Optional[str]) -> None:
    """Synchronous half of the save-time guard: length, compilability, and the
    example matching its own pattern."""
    if pattern is None:
        return
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A naming pattern may be at most {MAX_PATTERN_LENGTH} characters.",
        )
    try:
        _compiled(pattern)
    except re.error as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"That is not a valid regular expression: {e}",
        )
    if example is not None and not name_matches(pattern, example):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The example '{example}' does not match the pattern it illustrates. "
            "It appears in the error users see, so it has to be a name that works.",
        )


async def validate_pattern_async(
    pattern: Optional[str], example: Optional[str]
) -> None:
    """The full save-time guard, including the ReDoS probe.

    The pattern is tenant-admin-supplied and runs in the shared server process,
    so one catastrophic pattern pins a worker for EVERY tenant, and Python's
    `re` has no timeout. The probe runs the candidate against a short
    adversarial string (`_PROBE_STRING` — see its comment for why this is
    deliberately shorter than `environment.name`'s own 200-character column)
    off the event loop and refuses the pattern if that does not finish inside
    `_PROBE_TIMEOUT_SECONDS`.

    This is a footgun guard, NOT a security boundary: a determined admin can
    still write a pattern that is slow but finishes — the recorded upgrade
    path is the `regex` package's per-match `timeout=`, which needs a
    dependency-audit entry, not added here. And the guard bounds the
    *request*, not the CPU: `asyncio.wait_for` abandons the worker thread
    running `name_matches` rather than killing it, so a timed-out probe still
    leaves that thread spinning in the background. Accepted for a save-time
    guard against an accidental catastrophic pattern; not a defence against a
    deliberately adversarial one.
    """
    validate_pattern(pattern, example)
    if pattern is None:
        return
    try:
        await asyncio.wait_for(
            asyncio.to_thread(name_matches, pattern, _PROBE_STRING),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That pattern is too slow to evaluate safely — it backtracks "
            "catastrophically on a long name. Simplify nested quantifiers "
            "such as '(a+)+'.",
        )
