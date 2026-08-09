"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.

WHO CALLS WHICH HALF, AND WHY THE SYNCHRONOUS HALF IS SAFE
----------------------------------------------------------
There are two entry points and they protect different things:

* `validate_pattern_async` runs ONCE per naming-policy save. It is the only
  place a *never-before-seen* pattern is admitted, so it is where the ReDoS
  probe lives. It is async because the probe is a child process.
* `name_matches` / `evaluate_name` / `assert_name_allowed` are synchronous and
  run on the event loop, on every environment write and — from Tasks 5, 6 and
  7 — once per row of a tenant-wide re-evaluation or preview. They deliberately
  have NO timeout and NO thread hop.

That is safe only because of an invariant this module enforces at both ends:

1. No pattern reaches storage without terminating inside
   `_PROBE_TIMEOUT_SECONDS` against `_PROBE_STRING`, which is a worst case at
   the FULL `MAX_NAME_LENGTH` width — the same width as the column, so the
   probe input and the real input are the same size by construction.
2. No name longer than `MAX_NAME_LENGTH` is ever handed to the matcher
   (`name_matches` refuses it outright), and the API schemas cap `name` at the
   same 200 so an over-long name is a 422 long before it gets here.

Cost is monotonic in subject length for a fixed pattern, so a pattern that
finished within the budget at 200 characters finishes within it for every name
the column can hold. Bulk re-evaluation is therefore bounded by
`rows * _PROBE_TIMEOUT_SECONDS` in the pathological limit and by microseconds
in practice.

WHAT IS *NOT* BOUNDED, STATED PLAINLY
-------------------------------------
The probe is a footgun guard, not a security boundary, and two gaps remain:

* A pattern that is slow but finishes inside the budget is admitted, and that
  cost is then paid on every environment write. A tenant admin who wants to
  make their own tenant's saves take 0.9 seconds each can.
* A pattern stored BEFORE this guard existed, or written straight into the
  database, has never been probed. Nothing re-probes on read.

Python's `re` has no per-match timeout, so closing those needs the `regex`
package's `timeout=` argument, which needs a dependency-audit entry. Not done
here.
"""
import asyncio
import re
import sys
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

# environment.name is String(200). Everything in this module that has to pick a
# length picks THIS one: the probe subject, the defensive guard in
# `name_matches`, and (as a matching literal, with an agreement test) the
# `max_length` on EnvironmentCreate/EnvironmentUpdate.name. They must not drift
# apart — a probe narrower than the column measures a cost the real input never
# pays, which is exactly the hole this guard was rewritten to close.
MAX_NAME_LENGTH = 200

# The probe subject: a worst case at the FULL column width.
#
# Two properties matter, and the earlier 28-character version had only one.
#
# 1. It must FAIL TO MATCH. The trailing "!" is what forces a pattern like
#    `(a+)+$` to exhaust every partition of its nested quantifier before giving
#    up. A run of plain "a"s with nothing to break the match resolves on the
#    engine's first (greedy) attempt, in microseconds, with no backtracking.
#
# 2. It must be as long as a real name can be. Backtracking cost is not merely
#    "large at 28 and larger at 200" — for POLYNOMIAL patterns it is negligible
#    at 28 and lethal at 200, and polynomial is the shape a well-meaning admin
#    actually writes. Measured here:
#
#      [a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-(dev|uat|prod)
#        — an ordinary "segments separated by optional hyphens" convention —
#        0.005s at 28 characters, ~3s at 100, >90s at 200.
#      a*a*a*a*a*a*b
#        — ~53s at 200.
#
#    A 28-character probe accepted both in single-digit milliseconds. That is
#    the C1 hole: the probe was measuring a length the matcher never sees.
_PROBE_STRING = "a" * (MAX_NAME_LENGTH - 1) + "!"

# Total wall clock allowed for the child process, INCLUDING interpreter
# startup. Measured on this codebase's interpreter, `python -I -S -c` with only
# `re` imported costs ~11ms to spawn and exit, and an ordinary naming pattern
# against the 200-character subject finishes in ~13ms all-in — so ~99% of this
# budget is available to the match itself, and the margin over a legitimate
# pattern is roughly 70x. Every adversarial pattern named above is killed at
# the full second.
_PROBE_TIMEOUT_SECONDS = 1.0

# The child. It imports `re` and NOTHING from this application, so it costs
# interpreter startup rather than an app import graph — `-I` (isolated: no
# PYTHONPATH, no user site) and `-S` (no `site`, so no `.pth` hooks) make that
# structural rather than merely true today. Pattern and subject arrive as
# argv, and `create_subprocess_exec` runs no shell, so there is no quoting or
# injection surface.
#
# THE CHILD DELIBERATELY PRODUCES NO VERDICT. It discards the match result;
# its exit code says only "terminated" or "crashed". That is the answer to
# "`re.fullmatch` must be called in exactly one function": this is not a second
# place that decides whether a name matches, because it decides nothing — there
# is no verdict here that could disagree with `name_matches`. What the two DO
# share is the matcher method, because anchoring changes the cost profile
# (`search` on `(a+)+` returns instantly where `fullmatch` never does), and
# that is pinned behaviourally by
# `test_the_probe_measures_fullmatch_not_search`, not by this comment.
_PROBE_SCRIPT = "import re,sys\nre.compile(sys.argv[1]).fullmatch(sys.argv[2])\n"


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def name_matches(pattern: str, name: str) -> bool:
    """THE one regex call site in this application.

    `fullmatch`, not `search`: a pattern anchors by default, because a tenant
    writing `dev-.*` and having `xxdev-1` accepted is the likelier error.

    A name longer than `MAX_NAME_LENGTH` is refused WITHOUT being handed to the
    matcher. The column cannot hold such a name and the API schemas 422 it, so
    this is the third line of the same defence rather than a behaviour anyone
    should reach: it exists because the probe only proves a bound at 200
    characters, and every caller of this function is synchronous and on the
    event loop. Returning False (not raising) keeps `evaluate_name`'s contract
    intact — None still means "no pattern applies", and a name too long to
    store is not compliant with any convention.
    """
    name = name or ""
    if len(name) > MAX_NAME_LENGTH:
        return False
    return _compiled(pattern).fullmatch(name) is not None


async def _probe_terminates(pattern: str) -> bool:
    """Run `pattern` against `_PROBE_STRING` in a KILLABLE child process.

    True if the child finished cleanly inside `_PROBE_TIMEOUT_SECONDS`.

    A child process rather than `asyncio.to_thread`: `asyncio.wait_for` cancels
    the *await*, not the thread, so the previous implementation left the
    catastrophic match running in a `ThreadPoolExecutor` worker that nothing
    could stop. Worse, `to_thread` uses the loop's DEFAULT executor
    (`max_workers = min(32, cpu + 4)`), so ~32 such saves exhausted it
    permanently and the container then needed SIGKILL — and
    `ThreadPoolExecutor`'s `atexit` hook joins its workers, so the process
    could not exit on its own either. `.kill()` on a child has none of those
    properties: the CPU is reclaimed at once and the pool cannot be poisoned.
    """
    if not sys.executable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The naming pattern could not be safety-checked on this host "
            "(no interpreter available to run the check in), and an unchecked "
            "pattern is not stored.",
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            "-c",
            _PROBE_SCRIPT,
            pattern,
            _PROBE_STRING,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as e:
        # Fail CLOSED. Storing a pattern whose cost was never measured is the
        # one outcome this whole function exists to prevent, so a host that
        # cannot spawn the child refuses the save rather than waving it through.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The naming pattern could not be safety-checked ({e}), and an "
            "unchecked pattern is not stored.",
        )
    try:
        returncode = await asyncio.wait_for(
            proc.wait(), timeout=_PROBE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # reap it; a zombie would leak a PID per save
        return False
    # A non-zero exit means the match did not merely take too long, it blew up
    # — RecursionError or MemoryError on a pathological pattern. The pattern
    # already compiled in the parent, so `re.error` is not on this path. Treat
    # it as a refusal for the same reason as a timeout.
    return returncode == 0


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
    example matching its own pattern.

    Empty string and None are the SAME THING here, deliberately: `_pattern_in_force`
    treats a falsy pattern as no pattern, so gating this on `is not None` made
    `validate_pattern("", "foo")` complain that the example does not match a
    pattern that will never be applied to anything. Likewise an example of ""
    is a cleared form field, not an assertion that the empty name is valid.
    One opinion about empty strings, in one module.
    """
    if not pattern:
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
    if not example:
        return
    if len(example) > MAX_NAME_LENGTH:
        # Checked explicitly rather than left to `name_matches`' length guard,
        # which would return False and produce "the example does not match its
        # own pattern" for what is really a too-long example.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"An example may be at most {MAX_NAME_LENGTH} characters — it has "
            "to be a name an environment could actually be given.",
        )
    if not name_matches(pattern, example):
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
    `re` has no timeout. The probe runs the candidate against `_PROBE_STRING`
    — a non-matching subject at the FULL `MAX_NAME_LENGTH` width, so the probe
    and the real input are the same size — in a child process, and refuses the
    pattern if that child does not finish inside `_PROBE_TIMEOUT_SECONDS`.

    WHAT IS BOUNDED: the CPU. On timeout the child is killed and reaped, so a
    refused pattern costs at most `_PROBE_TIMEOUT_SECONDS` of one core and
    leaves nothing running. Nothing in the parent process is pinned, no thread
    pool is consumed, and the server stays killable. That is the whole reason
    this is a subprocess and not `asyncio.to_thread`; see `_probe_terminates`.

    WHAT IS NOT BOUNDED: see the module docstring. A pattern that is slow but
    finishes inside the budget is admitted and then pays that cost on every
    environment write, and nothing re-probes a pattern already in the database.
    Closing those needs a per-match timeout, which `re` does not have.
    """
    validate_pattern(pattern, example)
    if not pattern:
        return
    if not await _probe_terminates(pattern):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That pattern is too slow to evaluate safely — it backtracks "
            f"badly on a name of the full {MAX_NAME_LENGTH} characters an "
            "environment name may reach. Simplify nested quantifiers such as "
            "'(a+)+', and repeated optional groups such as "
            "'[a-z]*-?[a-z]*-?[a-z]*-?'.",
        )
