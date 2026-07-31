"""The frontend and backend must agree on which fields are sortable.

`docs/pagination.md` warns that a grid column left sortable whose field the
backend does not whitelist gives the user a header that looks clickable and 422s
the moment they click it — and that nothing in either codebase enforces it. This
file is that enforcement on the backend side; the frontend asserts its grids
against the same JSON.
"""
import json
from pathlib import Path

import pytest

from app.api.v1.bookings import BOOKING_SORTS
from app.api.v1.builds import BUILD_SORTS
from app.api.v1.change_requests import CHANGE_REQUEST_SORTS
from app.api.v1.deployments import DEPLOYMENT_SORTS
from app.api.v1.environments import ENVIRONMENT_SORTS
from app.api.v1.incidents import INCIDENT_SORTS
from app.api.v1.infrastructure_components import INFRASTRUCTURE_SORTS
from app.api.v1.releases import RELEASE_SORTS
from app.api.v1.systems import SYSTEM_SORTS

CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "constants"
    / "sortWhitelists.json"
)

# endpoint slug -> (whitelist, sorting() default, sorting() default_dir)
WHITELISTS = {
    "releases": (RELEASE_SORTS, "created_at", "desc"),
    "bookings": (BOOKING_SORTS, "start_date", "asc"),
    "environments": (ENVIRONMENT_SORTS, "name", "asc"),
    "change-requests": (CHANGE_REQUEST_SORTS, "scheduled_start", "desc"),
    "systems": (SYSTEM_SORTS, "name", "asc"),
    "infrastructure-components": (INFRASTRUCTURE_SORTS, "name", "asc"),
    "incidents": (INCIDENT_SORTS, "detected_at", "desc"),
    "deployments": (DEPLOYMENT_SORTS, "deployed_at", "desc"),
    "builds": (BUILD_SORTS, "commit_timestamp", "desc"),
}


def _contract() -> dict:
    # Fail rather than skip: a contract test that skips itself enforces nothing.
    assert CONTRACT.is_file(), f"contract file missing at {CONTRACT}"
    return json.loads(CONTRACT.read_text())


@pytest.mark.parametrize("endpoint", sorted(WHITELISTS))
def test_contract_matches_backend_whitelist(endpoint):
    sorts, default, default_dir = WHITELISTS[endpoint]
    entry = _contract()[endpoint]
    assert sorted(entry["sortable"]) == sorted(sorts)
    assert entry["default"] == default
    assert entry["default_dir"] == default_dir


def test_contract_declares_the_default_as_sortable():
    for endpoint, entry in _contract().items():
        assert entry["default"] in entry["sortable"], endpoint


def test_contract_has_exactly_the_expected_endpoints():
    # An endpoint in the file that the backend doesn't have would let a grid
    # offer sorts no server accepts.
    assert set(_contract()) == set(WHITELISTS)
