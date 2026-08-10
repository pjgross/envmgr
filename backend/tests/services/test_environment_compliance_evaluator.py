import logging
import time

import pytest
from fastapi import HTTPException

from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from app.services import environment_compliance_service as svc

# An ordinary "segments separated by optional hyphens" convention — the kind a
# well-meaning admin writes. Catastrophic under `re` (>90s against a
# 200-character name), microseconds under `regex`, which is the point of the
# engine swap. Kept, with its two transliterations below, because these are the
# patterns the two earlier probes waved through.
POLYNOMIAL_PATTERN = r"[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-?[a-z]*-(dev|uat|prod)"
POLYNOMIAL_UPPER = r"[A-Z]*-?[A-Z]*-?[A-Z]*-?[A-Z]*-?[A-Z]*-?[A-Z]*-(DEV|UAT|PROD)"
POLYNOMIAL_DIGITS = r"[0-9]*-?[0-9]*-?[0-9]*-?[0-9]*-?[0-9]*-?[0-9]*-(dev|uat|prod)"

# Patterns `regex` really is slow on, verified by measurement rather than by
# reputation. `(a+)+$` and friends are NOT among them — `regex` optimises those
# away, which is exactly why a probe can no longer be the safety boundary.
SLOW_LOWER = r"(a|a)*$"
SLOW_UPPER = r"(A|A)*$"
SLOW_DIGITS = r"(1|1)*$"


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
# One bounded engine
# ---------------------------------------------------------------------------


def test_there_is_exactly_one_matching_call_site():
    """The whole design rests on one engine with one opinion.

    Read the source rather than trusting a comment: `re` must not be imported
    at all, and `fullmatch` must appear exactly once outside a docstring — in
    `name_matches`.
    """
    import inspect

    source = inspect.getsource(svc)
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "import re\n" not in code and "import re " not in code
    assert code.count("fullmatch(") == 1, "more than one matcher call site"
    assert "fullmatch(" in inspect.getsource(svc.name_matches)


def test_every_match_is_handed_the_timeout():
    """The bound is the engine's, not ours — so the argument has to be there.

    Dropping `timeout=` leaves every functional test green and every match
    unbounded again, which is precisely how the last two rounds shipped.
    """
    import inspect

    body = inspect.getsource(svc.name_matches)
    assert "timeout=svc.MATCH_TIMEOUT_SECONDS" in body.replace("svc.", "") or (
        "timeout=MATCH_TIMEOUT_SECONDS" in body
    )


def test_the_probe_subjects_are_as_long_as_a_name_can_be():
    """The first review's hole was a 28-character probe measuring a cost the
    matcher never pays. Probe width and column width are the same number by
    construction."""
    assert svc.MAX_NAME_LENGTH == 200
    assert Environment.__table__.c.name.type.length == svc.MAX_NAME_LENGTH
    for label, subject in svc._PROBE_SUBJECTS.items():
        assert len(subject) == svc.MAX_NAME_LENGTH, label


def test_the_probe_covers_more_than_one_alphabet():
    """The second review's hole: 200 lowercase 'a's measures only patterns
    written over 'a'. Every uppercase or digit convention escaped it."""
    subjects = "".join(svc._PROBE_SUBJECTS.values())
    assert any(c.islower() for c in subjects)
    assert any(c.isupper() for c in subjects)
    assert any(c.isdigit() for c in subjects)
    assert "-" in subjects
    assert len(svc._PROBE_SUBJECTS) >= 4


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


def test_a_name_longer_than_the_column_is_never_handed_to_the_matcher():
    """The spreadsheet import calls create_environment_record directly, so the
    schema cap does not cover it. A 201-character name fully matches `[a-z]+`,
    so the only way to answer False is to short-circuit on length."""
    assert svc.name_matches(r"[a-z]+", "a" * svc.MAX_NAME_LENGTH) is True
    assert svc.name_matches(r"[a-z]+", "a" * (svc.MAX_NAME_LENGTH + 1)) is False


# ---------------------------------------------------------------------------
# A pattern that cannot be evaluated is NO PATTERN, never a refusal
# ---------------------------------------------------------------------------


def test_a_pattern_that_times_out_evaluates_to_none_not_false():
    """B2 must not mark an environment non-compliant because the server ran out
    of time on its own admin's regex."""
    policy = _policy(name_pattern=SLOW_LOWER)
    subject = "a" * (svc.MAX_NAME_LENGTH - 1) + "!"
    assert svc.name_matches(SLOW_LOWER, subject) is None
    assert svc.evaluate_name(policy, subject) is None


def test_a_pattern_that_times_out_refuses_nothing():
    """The other direction: a user's save must not fail because their admin
    wrote a slow pattern. `assert_name_allowed` tests `is not False`, so None
    is accepted; a truth test here would refuse."""
    policy = _policy(name_pattern=SLOW_LOWER)
    subject = "a" * (svc.MAX_NAME_LENGTH - 1) + "!"
    svc.assert_name_allowed(policy, submitted=subject, stored="something else")


def test_an_unevaluable_pattern_is_logged_at_error_with_tenant_and_pattern(caplog):
    """Failing open silently would hide a broken convention forever."""
    policy = _policy(tenant_id=4242, name_pattern=SLOW_LOWER)
    with caplog.at_level(logging.ERROR, logger=svc.__name__):
        svc.evaluate_name(policy, "a" * (svc.MAX_NAME_LENGTH - 1) + "!")
    assert caplog.records, "nothing logged"
    message = caplog.records[-1].getMessage()
    assert "4242" in message
    assert SLOW_LOWER in message


def test_a_stored_pattern_that_cannot_compile_is_no_pattern_rather_than_a_500():
    """Nothing re-validates a pattern on read, and Task 6 runs the stored one
    once per environment. A row written straight into the database must degrade
    to 'no pattern applies', not raise out of a sweep."""
    policy = _policy(name_pattern="[unclosed")
    assert svc.evaluate_name(policy, "anything") is None
    svc.assert_name_allowed(policy, submitted="anything", stored="other")


def test_a_stored_repeat_bomb_is_no_pattern_rather_than_a_hang():
    """The read path gets the compile ceiling too, or the sweep is the hole."""
    policy = _policy(name_pattern=r"(((a{1000}){1000}){1000})")
    started = time.perf_counter()
    assert svc.evaluate_name(policy, "anything") is None
    assert time.perf_counter() - started < 1.0


# ---------------------------------------------------------------------------
# The save-time probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pattern_slow_on_lower_case_is_refused():
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(SLOW_LOWER, None)
    assert exc.value.status_code == 422
    assert "too slow" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_pattern_slow_only_on_UPPER_CASE_is_refused():
    """Round two's hole, in one test. `(A|A)*$` costs microseconds against 200
    lowercase 'a's and never terminates against 200 'A's. Delete the upper-case
    probe subject and this is the test that fails."""
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(SLOW_UPPER, None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_pattern_slow_only_on_digits_is_refused():
    """Same hole, digits. A build-number naming convention is not exotic."""
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(SLOW_DIGITS, None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_the_probe_returns_promptly_rather_than_hanging():
    """Five bounded matches, so a refusal costs at most five budgets."""
    started = time.perf_counter()
    with pytest.raises(HTTPException):
        await svc.validate_pattern_async(SLOW_LOWER, None)
    elapsed = time.perf_counter() - started
    assert elapsed < len(svc._PROBE_SUBJECTS) * svc.MATCH_TIMEOUT_SECONDS + 1.0, elapsed


@pytest.mark.asyncio
async def test_an_ordinary_pattern_passes_the_probe():
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", "payments-uat-01")


@pytest.mark.asyncio
async def test_an_ordinary_pattern_costs_microseconds():
    """Five 200-character matches. If this approaches one budget the probe has
    stopped being free at policy-save frequency."""
    started = time.perf_counter()
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", None)
    assert time.perf_counter() - started < svc.MATCH_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# The patterns that escaped the two earlier probes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param(r"(a+)+$", id="the-textbook-exponential"),
        pytest.param(r"(a+)+", id="unanchored-textbook-exponential"),
        pytest.param(r"(x+)+$", id="round-two-the-error-messages-own-example"),
        pytest.param(r"(A+)+$", id="round-two-upper-case"),
        pytest.param(r"(1+)+$", id="round-two-digits"),
        pytest.param(POLYNOMIAL_PATTERN, id="round-one-polynomial"),
        pytest.param(POLYNOMIAL_UPPER, id="round-two-polynomial-upper-case"),
        pytest.param(POLYNOMIAL_DIGITS, id="round-two-polynomial-digits"),
        pytest.param(r"a*a*a*a*a*a*b", id="round-one-a-star-family"),
    ],
)
async def test_the_patterns_that_escaped_are_now_HARMLESS_not_merely_refused(pattern):
    """These are the exact patterns two rounds of review found escaping, and
    the honest outcome is not "they are now refused" — it is that they are no
    longer dangerous.

    `regex` optimises every one of them away, so all nine are ACCEPTED at save
    time and each evaluates in microseconds against every probe alphabet. Under
    `re` the same patterns cost 90 seconds or never terminated. Asserting a
    refusal here would be asserting a behaviour the engine does not have and
    does not need to have.

    What makes the class dead is not this list. It is that the match is
    bounded whatever the pattern — pinned by the timeout tests above, which use
    patterns `regex` genuinely is slow on.
    """
    await svc.validate_pattern_async(pattern, None)
    for label, subject in svc._PROBE_SUBJECTS.items():
        started = time.perf_counter()
        verdict = svc.name_matches(pattern, subject)
        elapsed = time.perf_counter() - started
        assert verdict is not None, f"{pattern!r} timed out on {label}"
        assert elapsed < svc.MATCH_TIMEOUT_SECONDS, f"{pattern!r} slow on {label}"


# ---------------------------------------------------------------------------
# Compilation: the one hole the engine swap opens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pattern",
    [
        pytest.param(r"(((a{1000}){1000}){1000})", id="three-levels-of-1000"),
        pytest.param(r"(a{1000}){1000}", id="two-levels-of-1000"),
        pytest.param(r"((a{100}){100})", id="two-levels-of-100"),
        pytest.param(r"a{1000000}", id="one-flat-million"),
    ],
)
async def test_a_repeat_bomb_is_refused_before_it_is_compiled(pattern):
    """`regex` EXPANDS bounded repeats at compile time where `re` does not, and
    no timeout covers compilation. Twenty-six characters of
    `(((a{1000}){1000}){1000})` costs `re` 0.2ms and costs `regex` unbounded
    time and hundreds of megabytes — a container killer, strictly worse than
    the request-level stall the swap removes.

    The assertion on elapsed time is the real one: the refusal has to happen
    BEFORE `regex.compile` sees the pattern, not after.
    """
    started = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(pattern, None)
    assert exc.value.status_code == 422
    assert time.perf_counter() - started < 1.0, "the bomb was compiled"


def test_the_repeat_ceiling_counts_NESTING_not_every_count_in_the_pattern():
    """`a{1000}b{1000}` and `(a{1000}){1000}` have the same naive product and
    costs three orders of magnitude apart — siblings add, nesting multiplies.
    A product of every count in the pattern cannot tell them apart, and would
    refuse ordinary conventions to catch bombs."""
    assert svc._repeat_weight(r"(a{1000}){1000}") == 1_000_000
    assert svc._repeat_weight(r"a{1000}b{1000}") == 2000
    # Realistic conventions all land in the low hundreds, far under the ceiling.
    for pattern in (
        r"[a-z]+-(dev|uat|prod)-\d{2}",
        r"[a-z]{1,50}-[a-z]{1,50}-[a-z]{1,50}",
        r"(?:[a-z]{1,20}-){1,10}(dev|uat|prod)",
        r"[a-z]{1,200}",
        POLYNOMIAL_PATTERN,
    ):
        assert svc._repeat_weight(pattern) <= svc.MAX_REPEAT_WEIGHT, pattern


def test_the_weight_scan_does_not_read_braces_it_should_not():
    """It is a conservative scanner, not a parser, but a `{` inside an escape
    or a character class is not a quantifier and must not be counted as one."""
    assert svc._repeat_weight(r"a\{1000\}") <= svc.MAX_REPEAT_WEIGHT
    assert svc._repeat_weight(r"[{1000}]x") <= svc.MAX_REPEAT_WEIGHT
    # A malformed pattern must not make the scan raise — the compiler is what
    # rejects it, and this runs first.
    for pattern in ("[unclosed", "((((", "a{", "a{,}", ")("):
        svc._repeat_weight(pattern)


# ---------------------------------------------------------------------------
# I-2: a tenant-supplied pattern must never be an HTTP 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_enormous_repeat_count_is_a_422_not_an_overflowerror():
    """`re.compile('a{4294967296}')` raises OverflowError, which sailed past an
    `except re.error` and reached the client as a 500."""
    for call in (
        lambda: svc.validate_pattern("a{4294967296}", None),
        svc.validate_pattern_async("a{4294967296}", None),
    ):
        with pytest.raises(HTTPException) as exc:
            result = call() if callable(call) else await call
            assert result is None
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_pattern_containing_a_space_is_accepted_not_a_500():
    """Recorded in review as a ValueError. It is not: 'a b' is a perfectly
    ordinary regex under both engines and always was. The 500 belonged to the
    subprocess, which no longer exists."""
    await svc.validate_pattern_async("a b", None)
    assert svc.name_matches("a b", "a b") is True


@pytest.mark.asyncio
async def test_a_pattern_containing_a_lone_surrogate_is_not_a_500():
    """This one was real: the probe passed the pattern to a child process as
    argv, and encoding '\\ud800' as UTF-8 raised UnicodeEncodeError out of the
    endpoint. In-process there is nothing to encode."""
    await svc.validate_pattern_async("a\ud800b", None)
    assert svc.name_matches("a\ud800b", "a\ud800b") is True


@pytest.mark.asyncio
async def test_no_tenant_supplied_pattern_escapes_as_a_non_http_error():
    """The general rule behind the three cases above. Anything a tenant can
    type is either accepted or a 422 — never an unhandled exception."""
    hostile = [
        "a{4294967296}",
        "a b",
        "a\ud800b",
        "[unclosed",
        "*a",
        "a{2,1}",
        r"(?P<1>a)",
        r"\p{NotARealProperty}",
        r"(?#unterminated",
        "(" * 200,
        "\\",
        "\x00",
        r"(?<=a*)b",
        r"[a-\d]",
        "(((a{1000}){1000}){1000})",
        SLOW_LOWER,
    ]
    for pattern in hostile:
        try:
            await svc.validate_pattern_async(pattern, None)
        except HTTPException as e:
            assert e.status_code == 422, pattern
        # Anything else propagates and fails the test, which is the assertion.


def test_the_stored_pattern_path_cannot_raise_either(caplog):
    """Same list, but through the read path, which has no HTTPException to hide
    behind: every one has to produce a verdict of None and refuse nothing.

    PAIRED WITH A SUBJECT, because unevaluability is a property of the pattern
    AND the name together, not of the pattern alone. Every entry but the last is
    unusable whatever it is handed — it cannot compile, or it blows the length
    or expansion ceiling before compilation is attempted. `SLOW_LOWER` is the
    exception: it compiles cleanly and answers in microseconds against a short
    name, so pairing it with 'dev-01' asserted None on a pattern that correctly
    returns False. It needs the full-width subject that actually makes it
    backtrack, which is the same one the timeout tests above use.
    """
    wide = "a" * (svc.MAX_NAME_LENGTH - 1) + "!"
    hostile = [
        ("a{4294967296}", "dev-01"),
        ("[unclosed", "dev-01"),
        ("*a", "dev-01"),
        (r"(?P<1>a)", "dev-01"),
        ("(((a{1000}){1000}){1000})", "dev-01"),
        ("a" * 501, "dev-01"),
        (SLOW_LOWER, wide),
    ]
    with caplog.at_level(logging.ERROR, logger=svc.__name__):
        for pattern, subject in hostile:
            assert svc.evaluate_name(_policy(name_pattern=pattern), subject) is None
            svc.assert_name_allowed(
                _policy(name_pattern=pattern), submitted=subject, stored="other"
            )
