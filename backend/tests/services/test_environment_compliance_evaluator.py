import time

import pytest
from fastapi import HTTPException

from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from app.services import environment_compliance_service as svc

# An ordinary "segments separated by optional hyphens" convention — the kind a
# well-meaning admin writes. Polynomial backtracking: ~0.005s against a
# 28-character name, ~3s at 100, >90s at 200. The old 28-character probe
# accepted it.
POLYNOMIAL_PATTERN = r"[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-(dev|uat|prod)"


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
    """The example is checked with `fullmatch`, not `search`.

    'XXpayments-01' is chosen precisely because `search` WOULD accept it — the
    previous fixture, 'NOT-A-MATCH', fails under both, so swapping the call to
    `search` left this test green while the anchoring it exists to pin was
    gone.
    """
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern(r"[a-z]+-\d{2}", "XXpayments-01")
    assert exc.value.status_code == 422
    assert "example" in exc.value.detail.lower()


def test_an_example_longer_than_a_name_can_be_is_refused_as_such():
    """Not as 'does not match its own pattern' — that would blame the regex for
    a too-long example."""
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern(r"[a-z]+", "a" * (svc.MAX_NAME_LENGTH + 1))
    assert exc.value.status_code == 422
    assert "at most 200 characters" in exc.value.detail


def test_an_empty_pattern_is_the_same_as_no_pattern():
    """`_pattern_in_force` treats a falsy pattern as no pattern, so gating the
    validator on `is not None` complained about an example illustrating a
    pattern that will never be applied to anything."""
    svc.validate_pattern("", "foo")  # must not raise
    svc.validate_pattern(None, "foo")


def test_an_empty_example_is_ignored_rather_than_checked():
    """A cleared form field is not an assertion that the empty name is valid."""
    svc.validate_pattern(r"[a-z]+-\d{2}", "")


@pytest.mark.asyncio
async def test_an_empty_pattern_skips_the_probe_too():
    await svc.validate_pattern_async("", "foo")
    await svc.validate_pattern_async(None, "foo")


# ---------------------------------------------------------------------------
# The ReDoS probe
# ---------------------------------------------------------------------------


def test_the_probe_subject_is_as_long_as_a_name_can_be():
    """The C1 hole was a 28-character probe measuring a cost the matcher never
    pays. Probe width and column width are now the same number by
    construction."""
    assert svc.MAX_NAME_LENGTH == 200
    assert len(svc._PROBE_STRING) == svc.MAX_NAME_LENGTH
    assert Environment.__table__.c.name.type.length == svc.MAX_NAME_LENGTH


def test_the_api_schemas_cap_the_name_at_the_same_length():
    """Without this cap a 100 kB name reaches the matcher before the column
    ever sees it — the amplifier that turns a slow pattern into a shared-process
    stall."""
    from app.api.v1.schemas.environment import EnvironmentCreate, EnvironmentUpdate

    for model in (EnvironmentCreate, EnvironmentUpdate):
        limits = [
            getattr(m, "max_length", None)
            for m in model.model_fields["name"].metadata
        ]
        assert svc.MAX_NAME_LENGTH in limits, model.__name__


@pytest.mark.asyncio
async def test_a_catastrophic_pattern_is_refused_by_the_probe():
    """The pattern runs in the shared server process, so one catastrophic
    pattern pins a worker for EVERY tenant and Python's `re` has no timeout."""
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(r"(a+)+$", None)
    assert exc.value.status_code == 422
    assert "too slow" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_polynomial_pattern_that_is_cheap_at_28_characters_is_refused():
    """C1. Exponential blowup is obvious at any length; POLYNOMIAL blowup is
    5ms at 28 characters and over 90 seconds at 200, and it is the shape a
    well-meaning admin actually writes."""
    assert svc.name_matches(POLYNOMIAL_PATTERN, "a" * 27 + "!") is False  # cheap
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(POLYNOMIAL_PATTERN, None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_polynomial_pattern_of_the_a_star_family_is_refused():
    """`a*a*a*a*a*a*b` — 53s at 200 characters, milliseconds at 28."""
    with pytest.raises(HTTPException):
        await svc.validate_pattern_async(r"a*a*a*a*a*a*b", None)


@pytest.mark.asyncio
async def test_the_probe_measures_fullmatch_not_search():
    """`(a+)+` (no `$`) is the discriminating case: `search` finds a match at
    offset 0 instantly, `fullmatch` never terminates. If the child ever drifts
    to `search` it would measure a cost `name_matches` does not pay, and wave
    this through."""
    with pytest.raises(HTTPException):
        await svc.validate_pattern_async(r"(a+)+", None)


@pytest.mark.asyncio
async def test_the_guard_returns_promptly_rather_than_hanging():
    """The point of killing a child instead of abandoning a thread: a refused
    pattern costs the timeout and nothing more."""
    started = time.perf_counter()
    with pytest.raises(HTTPException):
        await svc.validate_pattern_async(POLYNOMIAL_PATTERN, None)
    elapsed = time.perf_counter() - started
    assert elapsed < svc._PROBE_TIMEOUT_SECONDS + 2.0, elapsed


@pytest.mark.asyncio
async def test_an_ordinary_pattern_passes_the_probe():
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", "payments-uat-01")


@pytest.mark.asyncio
async def test_an_ordinary_pattern_costs_little_more_than_interpreter_startup():
    """~13ms measured. If this ever approaches the timeout, the probe has
    stopped being free at policy-save frequency."""
    started = time.perf_counter()
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", None)
    assert time.perf_counter() - started < svc._PROBE_TIMEOUT_SECONDS


def test_a_name_longer_than_the_column_is_never_handed_to_the_matcher():
    """The probe proves a bound at 200 characters and no further, and every
    caller of name_matches is synchronous and on the event loop. A 201-character
    name fully matches `[a-z]+`, so the only way to answer False is to
    short-circuit on length before compiling anything against it."""
    assert svc.name_matches(r"[a-z]+", "a" * svc.MAX_NAME_LENGTH) is True
    assert svc.name_matches(r"[a-z]+", "a" * (svc.MAX_NAME_LENGTH + 1)) is False
