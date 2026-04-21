"""Pydantic schemas for the tenant-admin scope-change-kind rule endpoints."""
from pydantic import BaseModel, ConfigDict


class ScopeChangeKindRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_kind: str
    counts_as_scope_change: bool


class ScopeChangeKindRuleUpsertItem(BaseModel):
    change_kind: str
    counts_as_scope_change: bool


class ScopeChangeKindRulesUpsertPayload(BaseModel):
    """Body for PUT /tenant/scope-change-rules — replaces the full config set."""
    rules: list[ScopeChangeKindRuleUpsertItem]
