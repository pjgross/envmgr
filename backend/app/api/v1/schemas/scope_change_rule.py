"""Pydantic schemas for the tenant-admin scope-change-kind rule endpoints."""
import re

from pydantic import BaseModel, ConfigDict, field_validator


# Slug shape for a change_kind — lowercase letter/digit start, then
# letters/digits/_/-. Length cap mirrors the DB column (String(20)).
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class ScopeChangeKindRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_kind: str
    counts_as_scope_change: bool


class ScopeChangeKindRuleUpsertItem(BaseModel):
    change_kind: str
    counts_as_scope_change: bool

    @field_validator("change_kind", mode="before")
    @classmethod
    def _normalise_kind(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("change_kind must be a string")
        kind = v.strip().lower()
        if not kind:
            raise ValueError("change_kind must not be empty")
        if len(kind) > 20:
            raise ValueError("change_kind must be 20 characters or fewer")
        if not _KIND_RE.match(kind):
            raise ValueError(
                "change_kind must start with a letter and contain only "
                "lowercase letters, digits, underscores, or hyphens"
            )
        return kind


class ScopeChangeKindRulesUpsertPayload(BaseModel):
    """Body for PUT /tenant/scope-change-rules — replaces the full config set."""
    rules: list[ScopeChangeKindRuleUpsertItem]
