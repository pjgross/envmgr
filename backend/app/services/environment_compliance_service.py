"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.
"""
from sqlalchemy import String, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.environment import Environment


def custom_field_missing_clause(field_key: str) -> ColumnElement[bool]:
    """True when `custom_fields` does not supply a usable value for `field_key`.

    Absent, JSON null, and whitespace-only all count as missing; `0` and `false`
    do not — a `number` custom field storing zero is a supplied value, and
    `trim()` over the text form of `0` is `'0'`, which is non-empty.

    `Environment.custom_fields[field_key]` is dialect-compiled by SQLAlchemy:
    `->>` on PostgreSQL, `json_extract` on SQLite. `field_key` is a bound
    parameter, never interpolated.
    """
    value = Environment.custom_fields[field_key].as_string()
    return or_(
        Environment.custom_fields.is_(None),
        value.is_(None),
        func.trim(func.cast(value, String)) == "",
    )
