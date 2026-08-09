"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.

ONE ENGINE, AND WHY IT IS `regex` RATHER THAN `re`
--------------------------------------------------
The naming pattern is written by a tenant admin and evaluated in a shared
multi-tenant process, so every match against it has to be bounded. `re` has no
per-match timeout; `regex` (PyPI `regex`) does, and is a syntax superset of
`re`, so patterns written for one work in the other. There is exactly ONE
matching call site — `name_matches` — and this module imports no other regex
engine, so there is no second opinion anywhere for the first to disagree with.

WHAT IS BOUNDED
---------------
* EVERY match, wherever it is called from — the save-time check, every
  environment write, and once per row of a tenant-wide re-evaluation — by
  `MATCH_TIMEOUT_SECONDS`, enforced by the engine itself. Two earlier designs
  bounded only the *policy save* and left the write path and the sweep with no
  bound at all.
* Compilation, by `MAX_PATTERN_LENGTH` and `MAX_REPEAT_WEIGHT`. Compilation
  happens before any match and no timeout covers it; see `_repeat_weight`.
* The subject, by `MAX_NAME_LENGTH`. `name_matches` refuses a longer name
  without handing it to the matcher.

WHAT IS NOT BOUNDED, STATED PLAINLY
-----------------------------------
* A pattern that is slow but finishes inside the budget is admitted, and that
  cost is paid on every write. A tenant admin can make their own tenant's saves
  cost up to `MATCH_TIMEOUT_SECONDS` each.
* The budget is per MATCH, not per request or per sweep. A re-evaluation of N
  environments against a pathological pattern costs up to
  `N * MATCH_TIMEOUT_SECONDS`. It finishes; it is not fast.
* `validate_pattern_async`'s probe is a COURTESY, not the safety boundary. It
  tries a handful of alphabets so an admin is told at save time rather than
  discovering later that their convention silently evaluates to nothing. It
  cannot cover every subject a pattern might be slow on, and it does not need
  to, because the per-match timeout covers what it misses.

THREE WRITE PATHS SET `environment.name`, AND THE SCHEMAS CAP ONLY TWO
-----------------------------------------------------------------------
`EnvironmentCreate`/`EnvironmentUpdate` carry `max_length=200`, matching
`MAX_NAME_LENGTH` and the column. `excel_import_service.import_environments`
is the third path: it calls `environment_service.create_environment_record`
directly with a spreadsheet cell, so no Pydantic cap applies to it. That is why
`name_matches` carries its own length guard rather than trusting the schemas —
and it is a real gap in the *import*, not merely a theoretical one, left open
deliberately here rather than widened into this task.
"""
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import regex
from fastapi import HTTPException, status
from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.api.v1.schemas.environment_naming_policy import (
    CUSTOM_FIELD_PREFIX,
    FIXED_ATTRIBUTES,
)
from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from app.services.custom_field_service import list_definitions

logger = logging.getLogger(__name__)

# Mirrors CustomFieldDefinition's own validation
# (app/api/v1/schemas/custom_field.py: FIELD_KEY_RE). Every field_key that can
# reach this function has already passed that regex — this is a second,
# independent check on the same charset, not a wider allowance. Compiled with
# `regex` like everything else here: one engine in this module, so there is
# never a question about which one a given expression is being read by.
_SAFE_FIELD_KEY_RE = regex.compile(r"^[a-z][a-z0-9_]*$")


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

# environment.name is String(200). Everything here that has to pick a length
# picks THIS one: the probe subjects, the guard in `name_matches`, and (as a
# matching literal, with an agreement test) the `max_length` on
# EnvironmentCreate/EnvironmentUpdate.name.
MAX_NAME_LENGTH = 200

# The budget for ONE match, handed to the engine. Every call goes through it.
#
# Margin, measured on this codebase's interpreter against the 200-character
# probe subjects: an ordinary naming pattern costs ~0.003 ms per match once
# compiled, so the budget is ~30,000x a legitimate match. The engine overshoots
# it by 0.1-0.25 ms when it does fire, so a refused pattern really does cost
# about this and not more.
#
# It is deliberately ONE number for the save-time probe and for match time.
# Two budgets would let a pattern pass the save check and then time out on
# every write, which is the exact shape of failure this module keeps producing.
MATCH_TIMEOUT_SECONDS = 0.1

# The probe subjects: worst cases at the FULL column width, in several
# alphabets.
#
# Two properties matter, and each earlier version had only one of them.
#
# 1. Each must FAIL TO MATCH. The trailing "!" is what forces a pattern like
#    `(a|a)*$` to exhaust its alternatives before giving up. A clean run of
#    "a"s with nothing to break the match resolves on the engine's first
#    attempt, in microseconds.
#
# 2. There must be MORE THAN ONE ALPHABET. A single subject of 200 lowercase
#    "a"s measures only patterns written over "a". `(x+)+$`, `(A|A)*$` and
#    `(1|1)*$` are all invisible to it — and an uppercase or digit naming
#    convention is perfectly ordinary. That was the second review's finding and
#    it is why this is a dict and not a string.
#
# What the probe still cannot do is cover every alphabet: `(q|q)*$` is slow
# only against a subject of "q"s, and nothing here contains one. That is fine,
# and is the difference between this design and the two before it — a pattern
# the probe misses is caught by the per-match timeout at the moment it is used,
# rather than pinning the process.
_PROBE_SUBJECTS = {
    "lower-case": "a" * (MAX_NAME_LENGTH - 1) + "!",
    "upper-case": "A" * (MAX_NAME_LENGTH - 1) + "!",
    "digits": "1" * (MAX_NAME_LENGTH - 1) + "!",
    "hyphens": "-" * (MAX_NAME_LENGTH - 1) + "!",
    "mixed": ("aA1-" * MAX_NAME_LENGTH)[: MAX_NAME_LENGTH - 1] + "!",
}

# The ceiling on a pattern's expanded size, checked BEFORE it is compiled.
#
# `regex` expands bounded repeats at compile time where `re` does not, and no
# timeout covers compilation. Measured here, cost is linear in the expanded
# node count and indifferent to how it is reached:
#
#     weight      compile    peak RAM
#     1e3          0.004s       0.3MB
#     1e4          0.033s       2.8MB
#     1e5          0.30s         26MB
#     1e6          3.1s         250MB
#
# So `(((a{1000}){1000}){1000})` — twenty-six characters, well under
# MAX_PATTERN_LENGTH, and compiled by `re` in 0.2 ms — takes unbounded time and
# memory under `regex`. It is the one hole the engine swap OPENS, and it is
# worse than the one it closes: memory exhaustion takes the container down, not
# one request.
#
# 1000 is generous by a wide margin and refuses nothing useful. A pattern's
# expanded weight is roughly the longest subject it can usefully match, and a
# name is at most 200 characters, so every realistic convention lands in the
# low hundreds: `[a-z]{1,50}-[a-z]{1,50}-[a-z]{1,50}` weighs 152,
# `(?:[a-z]{1,20}-){1,10}(dev|uat|prod)` weighs ~215, `\d{2}` weighs 2. At this
# ceiling a compiled pattern costs at most ~4 ms and ~0.3 MB, so `_compiled`'s
# 256-entry cache retains at most ~77 MB even if every entry is at the limit.
MAX_REPEAT_WEIGHT = 1000


def _repeat_weight(pattern: str) -> int:
    """A CONSERVATIVE upper bound on how far `regex` will expand `pattern`.

    Not a parser and not exact — it only ever over-estimates, which is the safe
    direction for a ceiling. Sibling items ADD, a bounded repeat MULTIPLIES the
    item before it, and unbounded quantifiers (`*`, `+`, `?`) expand to nothing
    so they count as 1. That distinction is the whole point: `a{1000}b{1000}`
    costs 6 ms (weight 2000, they are siblings) while `(a{1000}){1000}` costs
    3 s (weight 1e6, they are nested), and a naive product of every count in
    the pattern cannot tell those apart — it would refuse the cheap one.

    Escapes and character classes are consumed whole so a `{` inside either is
    never read as a quantifier. A malformed pattern cannot make this raise; it
    returns some number and the compiler then rejects the pattern properly.
    """
    stack: list[int] = []  # accumulated weight of each open group
    total = 0  # accumulated weight of the current level
    last = 0  # weight of the most recent item, awaiting a quantifier
    i, n = 0, len(pattern)

    def flush() -> None:
        nonlocal total, last
        total += last
        last = 0

    while i < n:
        c = pattern[i]
        if c == "\\":
            flush()
            last = 1
            i += 2
        elif c == "[":
            flush()
            last = 1
            i += 1
            if i < n and pattern[i] == "^":
                i += 1
            if i < n and pattern[i] == "]":  # a literal ] in first position
                i += 1
            while i < n and pattern[i] != "]":
                i += 2 if pattern[i] == "\\" else 1
            i += 1
        elif c == "(":
            flush()
            stack.append(total)
            total = 0
            i += 1
        elif c == ")":
            flush()
            inner = total
            total = stack.pop() if stack else 0
            last = max(inner, 1)
            i += 1
        elif c == "{":
            close = pattern.find("}", i)
            body = pattern[i + 1 : close] if close != -1 else ""
            parts = body.split(",")
            counts = [int(p) for p in parts if p.strip().isdigit()]
            if close != -1 and len(parts) <= 2 and (counts or body.strip() == ""):
                # A real quantifier. `{m,}` and `{,n}` both give one count.
                last *= max(counts) if counts else 1
                i = close + 1
            else:  # a literal brace, e.g. `a\{2\}` after unescaping, or `{x}`
                flush()
                last = 1
                i += 1
        else:
            flush()
            last = 1
            i += 1
    flush()
    # Anything left unclosed still has to be counted; the pattern will fail to
    # compile, but this function must not under-report on the way there.
    return total + sum(stack)


class _PatternUnusable(Exception):
    """This pattern cannot be turned into a matcher at all.

    Carries the sentence a tenant admin should read. `validate_pattern` renders
    it as a 422; `name_matches` — which may be handed a pattern that never went
    through the validator, straight from the database — treats it as "no
    pattern applies", the same as a match that times out.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> regex.Pattern:
    """The ONE place a pattern becomes a matcher, with the whole compile-time
    ceiling attached to it.

    Length, then expansion weight, then compilation — in that order, each cheap
    enough to be safe given the ones before it. Both entry points go through
    here, so a bomb written straight into the database is refused on the READ
    path too and not only at save; the validator and the matcher cannot end up
    disagreeing about which patterns are usable, because there is one answer.

    `lru_cache` does not cache exceptions, so a bad pattern re-runs the cheap
    checks on every call and never reaches the expensive one. A good pattern
    compiles once.

    Every exception from `regex.compile` is caught, not just the engine's own
    `error` type: compiling an arbitrary tenant-supplied string is exactly the
    operation where any failure is the input rather than our bug, and
    `a{4294967296}` raised `OverflowError` straight past an `except re.error`
    and reached the client as an HTTP 500. `BaseException` is deliberately not
    caught, so cancellation still propagates.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise _PatternUnusable(
            f"A naming pattern may be at most {MAX_PATTERN_LENGTH} characters."
        )
    weight = _repeat_weight(pattern)
    if weight > MAX_REPEAT_WEIGHT:
        raise _PatternUnusable(
            "That pattern repeats itself too many times to compile safely — "
            f"it expands to roughly {weight} elements and the ceiling is "
            f"{MAX_REPEAT_WEIGHT}. Nested counted repeats multiply, so "
            "'(a{100}){100}' is a hundred times bigger than it looks. An "
            f"environment name is at most {MAX_NAME_LENGTH} characters, so no "
            "useful convention needs to be this large."
        )
    try:
        return regex.compile(pattern)
    except Exception as e:
        raise _PatternUnusable(f"That is not a valid regular expression: {e}")


def name_matches(pattern: str, name: str) -> Optional[bool]:
    """THE one regex call site in this application.

    `fullmatch`, not `search`: a pattern anchors by default, because a tenant
    writing `dev-.*` and having `xxdev-1` accepted is the likelier error.

    Returns True, False, or **None when the pattern could not be evaluated** —
    either it is unusable at all (`_PatternUnusable`) or the match did not
    finish inside `MATCH_TIMEOUT_SECONDS`. None is not a third verdict: it is
    the same "no pattern applies" that `evaluate_name` already returns for a
    tenant with no policy, and every caller treats it that way. See `_verdict`.

    A name longer than `MAX_NAME_LENGTH` is refused WITHOUT being handed to the
    matcher. Two of the three write paths cap it at the schema (the spreadsheet
    import does not — see the module docstring), so this is the backstop for
    the one that does not, and it answers False rather than raising because a
    name too long to store is not compliant with any convention.
    """
    name = name or ""
    if len(name) > MAX_NAME_LENGTH:
        return False
    try:
        compiled = _compiled(pattern)
    except _PatternUnusable:
        return None
    try:
        return compiled.fullmatch(name, timeout=MATCH_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        return None


def _pattern_in_force(policy: Optional[EnvironmentNamingPolicy]) -> Optional[str]:
    if policy is None or not policy.is_enabled or not policy.name_pattern:
        return None
    return policy.name_pattern


def _verdict(
    policy: EnvironmentNamingPolicy, pattern: str, name: str
) -> Optional[bool]:
    """`name_matches`, plus the one decision about what an UNEVALUABLE pattern
    means.

    A PATTERN THE SERVER CANNOT EVALUATE IS TREATED AS NO PATTERN AT ALL:
    verdict None, nothing refused, and an error logged naming the tenant, the
    pattern and the reason so an operator can see it.

    B2 is advisory. It must not mark an environment non-compliant because the
    server ran out of time on its own admin's regex, and it must not refuse a
    user's save for the same reason — the user did nothing wrong and has no way
    to fix it. Failing open here is not a weakened guarantee: a stored pattern
    has already been through `validate_pattern_async`, so reaching this branch
    means the pattern was written straight to the database, or predates the
    guard, or is slow on a subject the probe's alphabets did not cover. In all
    three the honest answer is "this convention could not be applied", not
    "this name is wrong".
    """
    verdict = name_matches(pattern, name)
    if verdict is None:
        logger.error(
            "Environment naming pattern could not be evaluated and was treated "
            "as no pattern at all — no name was judged and none was refused. "
            "tenant_id=%s pattern=%r reason=%s",
            getattr(policy, "tenant_id", None),
            pattern,
            _unusable_reason(pattern),
        )
    return verdict


def _unusable_reason(pattern: str) -> str:
    """Why `name_matches` answered None. Error path only."""
    try:
        _compiled(pattern)
    except _PatternUnusable as e:
        return e.detail
    return f"the match did not finish within {MATCH_TIMEOUT_SECONDS}s"


def evaluate_name(
    policy: Optional[EnvironmentNamingPolicy], name: str
) -> Optional[bool]:
    """The verdict stored on `environment.name_compliant`.

    None means NO PATTERN APPLIES — not unknown, not failing. A pattern that
    times out returns None for that reason too; see `_verdict`.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None:
        return None
    return _verdict(policy, pattern, name)


def assert_name_allowed(
    policy: Optional[EnvironmentNamingPolicy],
    submitted: str,
    stored: Optional[str],
) -> None:
    """The ONLY refusal in the whole of B2, and only for a CHANGED name.

    A full-form save re-sending an existing bad name is accepted — otherwise
    activating a policy freezes every non-conforming environment's next save,
    the same shape as A1's archived-FK-value carve-out.

    `is not False` rather than a truth test, so a timed-out match (None) is
    accepted rather than refused: see `_verdict`.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None or submitted == stored:
        return
    if _verdict(policy, pattern, submitted) is not False:
        return
    example = policy.name_pattern_example
    hint = f" For example: '{example}'." if example else ""
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"'{submitted}' does not match this tenant's environment naming "
        f"convention ({pattern}).{hint}",
    )


def _refuse_as_too_slow() -> None:
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "That pattern is too slow to evaluate safely — it does not finish "
        f"within {MATCH_TIMEOUT_SECONDS}s against a name of the full "
        f"{MAX_NAME_LENGTH} characters an environment name may reach. "
        "Simplify nested quantifiers such as '(a|a)*', and repeated "
        "overlapping alternations such as '(?:a|b|ab)*'.",
    )


def validate_pattern(pattern: Optional[str], example: Optional[str]) -> None:
    """Synchronous half of the save-time guard: length, expansion weight,
    compilability, and the example matching its own pattern.

    Empty string and None are the SAME THING here, deliberately: `_pattern_in_force`
    treats a falsy pattern as no pattern, so gating this on `is not None` made
    `validate_pattern("", "foo")` complain that the example does not match a
    pattern that will never be applied to anything. Likewise an example of ""
    is a cleared form field, not an assertion that the empty name is valid.
    One opinion about empty strings, in one module.
    """
    if not pattern:
        return
    try:
        _compiled(pattern)
    except _PatternUnusable as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, e.detail)
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
    verdict = name_matches(pattern, example)
    if verdict is None:
        # The example itself blew the budget. Report it as what it is — a slow
        # pattern — rather than as an example that does not match.
        _refuse_as_too_slow()
    if not verdict:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The example '{example}' does not match the pattern it illustrates. "
            "It appears in the error users see, so it has to be a name that works.",
        )


async def validate_pattern_async(
    pattern: Optional[str], example: Optional[str]
) -> None:
    """The full save-time guard: `validate_pattern` plus a multi-alphabet probe.

    Still `async def` although nothing here awaits: it is the callable the API
    layer holds, its 422 contract is unchanged, and awaiting a synchronous body
    costs nothing. It used to spawn a child process, which is where the name
    came from.

    THE PROBE IS A COURTESY, NOT THE SAFETY BOUNDARY. Every match this
    application performs is bounded by the engine, so a slow pattern that slips
    through costs one timeout and a logged error rather than a pinned process.
    What the probe buys is that the admin is told NOW, at the moment they write
    the pattern, instead of their convention silently evaluating to nothing
    later. Two earlier designs treated a probe as the guarantee and were wrong
    both times, because a probe can only ever try subjects someone thought of.

    Cost: five matches, each bounded, so at most
    `5 * MATCH_TIMEOUT_SECONDS` = half a second of event loop for a pattern
    that is slow on every alphabet, and ~0.02 ms for one that is not.
    """
    validate_pattern(pattern, example)
    if not pattern:
        return
    for subject in _PROBE_SUBJECTS.values():
        if name_matches(pattern, subject) is None:
            _refuse_as_too_slow()


# ---------------------------------------------------------------------------
# The policy itself: loading it, saving it, and re-judging the estate
# ---------------------------------------------------------------------------


async def load_policy(
    db: AsyncSession, tenant_id: int
) -> Optional[EnvironmentNamingPolicy]:
    """The tenant's policy row, or None if it has never saved one.

    There is no `deleted_at` on this table and no DELETE path — `is_enabled` is
    the off switch, so None means "never configured", never "removed".
    """
    return (
        await db.execute(
            select(EnvironmentNamingPolicy).where(
                EnvironmentNamingPolicy.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def _assert_attributes_known(
    db: AsyncSession, tenant_id: int, attributes: list[str]
) -> None:
    """Every entry is either one of the three fixed attributes or a `cf:` key
    this tenant actually defines.

    A typo'd key would otherwise mark the whole estate non-compliant against a
    field that does not exist, with nothing on any screen to explain why — the
    attribute check has no equivalent of the naming pattern's worked example.
    """
    defined = {d.field_key for d in await list_definitions(db, tenant_id, "environment")}
    for attr in attributes:
        if attr in FIXED_ATTRIBUTES:
            continue
        if attr.startswith(CUSTOM_FIELD_PREFIX):
            key = attr[len(CUSTOM_FIELD_PREFIX) :]
            if key in defined:
                continue
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"'{key}' is not a custom field defined for environments in "
                "this tenant.",
            )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{attr}' is not an attribute a naming policy can require. "
            f"Use one of {sorted(FIXED_ATTRIBUTES)}, or 'cf:<field_key>'. "
            "Tier is always required by the schema, so it cannot be listed here.",
        )


async def upsert_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    is_enabled: bool,
    name_pattern: Optional[str],
    name_pattern_example: Optional[str],
    required_attributes: list[str],
    grace_days: int,
) -> EnvironmentNamingPolicy:
    """Save the tenant's one policy row and re-judge every environment against it.

    VALIDATION RUNS BEFORE ANYTHING IS MUTATED, both halves of it, so a refused
    save leaves no partially-applied rule behind. The pattern goes through
    Task 3's `validate_pattern_async` rather than being re-decided here — one
    module owns every regex decision, and an endpoint that made its own would
    be the second opinion the whole design exists to avoid.

    The recompute is what makes the verdict trustworthy. `name_compliant` is
    stored, so without it every environment would keep the verdict of a policy
    that no longer exists — and the disable path matters as much as the enable
    path: turning a policy off must return the estate to "no rule applies", not
    freeze the last judgement it made.
    """
    await validate_pattern_async(name_pattern, name_pattern_example)
    await _assert_attributes_known(db, tenant_id, required_attributes)

    policy = await load_policy(db, tenant_id)
    if policy is None:
        policy = EnvironmentNamingPolicy(tenant_id=tenant_id)
        db.add(policy)
        rule_changed = bool(name_pattern) or bool(required_attributes)
    else:
        rule_changed = policy.name_pattern != name_pattern or list(
            policy.required_attributes or []
        ) != list(required_attributes)

    policy.is_enabled = is_enabled
    policy.name_pattern = name_pattern
    policy.name_pattern_example = name_pattern_example
    policy.required_attributes = list(required_attributes)
    policy.grace_days = grace_days
    if rule_changed:
        # Bumped in EITHER direction: "stricter" is not a decidable property of
        # a regex change, and granting fresh grace for a relaxation is harmless.
        # Deliberately NOT bumped by grace_days, is_enabled or the example —
        # none of those changes what is being asked of an environment, and
        # bumping on them would hand a fresh grace period to the whole estate
        # every time an admin corrected a typo in the example.
        policy.effective_from = datetime.now(timezone.utc)

    await db.flush()
    await recompute_tenant(db, tenant_id, policy)
    await db.refresh(policy)
    return policy


async def recompute_tenant(
    db: AsyncSession, tenant_id: int, policy: Optional[EnvironmentNamingPolicy]
) -> int:
    """Re-evaluate every live environment's stored name verdict. Returns the count.

    Bounded by one tenant's estate and one flush, and it runs inline on the
    policy save because that is the only moment the answer can change for every
    row at once. There is no scheduler and nothing to invalidate.

    It calls `evaluate_name` per row rather than matching in SQL because no
    regex is portable across SQLite and PostgreSQL — that is the whole reason
    this verdict is stored rather than computed on read. The per-match timeout
    is what keeps a pathological pattern from turning this loop into a hang;
    see the module docstring on what that does and does not bound.

    Passing `policy=None`, or a policy that is disabled or has no pattern,
    returns every verdict to NULL — "no rule applies", which counts as
    compliant everywhere it is read.
    """
    envs = (
        (
            await db.execute(
                select(Environment).where(
                    Environment.tenant_id == tenant_id,
                    Environment.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for env in envs:
        env.name_compliant = evaluate_name(policy, env.name)
    await db.flush()
    return len(envs)
