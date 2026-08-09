"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.
"""
import re

from sqlalchemy import String, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.environment import Environment

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
