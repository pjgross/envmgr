"""The frontend and backend must agree on which API-key scopes exist.

`ApiKeyCreate.scopes` is validated against `app.core.api_scopes.KNOWN_SCOPES`
(see `app/api/v1/schemas/api_key.py`); the frontend's `ApiKeyCreateDialog.tsx`
scope picker is generated from `frontend/src/constants/apiKeyScopes.json`.
This file is the enforcement that the two cannot drift — the same pattern
`test_sort_whitelist_contract.py` uses for `sortWhitelists.json`, including
failing outright (never skipping) when the contract file is missing.
"""
import json
from pathlib import Path

from app.core.api_scopes import KNOWN_SCOPES

CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "constants"
    / "apiKeyScopes.json"
)


def _contract() -> dict:
    # Fail rather than skip: a contract test that skips itself enforces nothing.
    assert CONTRACT.is_file(), f"contract file missing at {CONTRACT}"
    return json.loads(CONTRACT.read_text())


def test_frontend_scope_keys_match_backend_known_scopes():
    frontend = _contract()
    assert set(frontend) == set(KNOWN_SCOPES)


def test_frontend_scope_labels_match_backend_labels():
    # Not required by the task, but cheap to assert and keeps the picker's
    # copy from silently diverging from the backend's own description.
    assert _contract() == KNOWN_SCOPES
