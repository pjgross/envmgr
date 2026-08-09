import pytest
from fastapi import HTTPException

from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from app.services import environment_compliance_service as svc


def _policy(**kw) -> EnvironmentNamingPolicy:
    defaults = dict(
        tenant_id=1,
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    defaults.update(kw)
    return EnvironmentNamingPolicy(**defaults)


def test_a_pattern_anchors_by_default():
    """fullmatch, not search: a tenant writing `dev-.*` and having `xxdev-1`
    accepted is the likelier error."""
    assert svc.name_matches(r"dev-.*", "dev-1") is True
    assert svc.name_matches(r"dev-.*", "xxdev-1") is False


def test_evaluate_name_returns_none_when_no_pattern_applies():
    assert svc.evaluate_name(None, "anything") is None
    assert svc.evaluate_name(_policy(is_enabled=False), "nope") is None
    assert svc.evaluate_name(_policy(name_pattern=None), "nope") is None


def test_evaluate_name_judges_when_a_pattern_applies():
    assert svc.evaluate_name(_policy(), "payments-uat-01") is True
    assert svc.evaluate_name(_policy(), "Payments UAT 1") is False


def test_an_unchanged_bad_name_is_accepted():
    """Activating a policy must not freeze every non-conforming environment's
    next save. A full-form PATCH re-sending the stored name is accepted."""
    svc.assert_name_allowed(_policy(), submitted="legacy box", stored="legacy box")


def test_a_changed_name_that_still_fails_is_refused():
    with pytest.raises(HTTPException) as exc:
        svc.assert_name_allowed(_policy(), submitted="legacy box 2", stored="legacy box")
    assert exc.value.status_code == 422
    # The example is in the message, so the 422 teaches a name that works.
    assert "payments-uat-01" in exc.value.detail


def test_a_new_name_is_judged_against_the_pattern():
    with pytest.raises(HTTPException):
        svc.assert_name_allowed(_policy(), submitted="nope", stored=None)
    svc.assert_name_allowed(_policy(), submitted="payments-uat-01", stored=None)


def test_no_policy_refuses_nothing():
    svc.assert_name_allowed(None, submitted="anything at all", stored=None)
    svc.assert_name_allowed(_policy(is_enabled=False), submitted="!!!", stored=None)


def test_an_invalid_regex_is_refused_at_save():
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern("[unclosed", None)
    assert exc.value.status_code == 422


def test_a_pattern_longer_than_500_characters_is_refused():
    with pytest.raises(HTTPException):
        svc.validate_pattern("a" * 501, None)


def test_an_example_its_own_pattern_rejects_is_refused():
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern(r"[a-z]+-\d{2}", "NOT-A-MATCH")
    assert exc.value.status_code == 422
    assert "example" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_catastrophic_pattern_is_refused_by_the_probe():
    """The pattern runs in the shared server process, so one catastrophic
    pattern pins a worker for EVERY tenant and Python's `re` has no timeout."""
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(r"(a+)+$", None)
    assert exc.value.status_code == 422
    assert "too slow" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_an_ordinary_pattern_passes_the_probe():
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", "payments-uat-01")
