from app.services.rollback_plan_service import rollup


class _P:
    """A stand-in carrying only what rollup reads — no database needed."""
    def __init__(self, reversibility):
        self.reversibility = reversibility


def test_the_worst_component_decides():
    assert rollup([_P("reversible"), _P("irreversible"), _P("lossy")]) == "irreversible"
    assert rollup([_P("reversible"), _P("lossy")]) == "lossy"
    assert rollup([_P("reversible"), _P("reversible")]) == "reversible"


def test_no_plans_means_no_verdict():
    """None, not 'reversible' — an unanswered question must never read as a
    reassuring answer."""
    assert rollup([]) is None


def test_an_unknown_value_never_wins_silently():
    """A value outside the vocabulary must not be ordered as if it were safe.
    It sorts as the WORST, so a bad row is loud rather than invisible."""
    assert rollup([_P("reversible"), _P("nonsense")]) == "nonsense"
