"""Pure comparison logic — no database.

Host names differ between environments by design (sit-app-01 vs uat-app-01),
so comparing identity would mark every subsystem different. These functions
define what "the hosts differ" actually means.
"""
from app.services.environment_comparison import difference_kinds, host_shape


def test_host_shape_counts_duplicates():
    shape = host_shape([("server", "primary"), ("server", "primary")])
    assert shape == [{"component_type": "server", "role": "primary", "count": 2}]


def test_host_shape_is_order_independent():
    # THE test for this module: two environments list the same hosts in a
    # different order and must compare equal.
    a = host_shape([("server", "primary"), ("cache", None)])
    b = host_shape([("cache", None), ("server", "primary")])
    assert a == b


def test_host_shape_handles_a_null_role():
    # role is nullable on environment_subsystem_host; sorting must not raise.
    assert host_shape([("cache", None)]) == [
        {"component_type": "cache", "role": None, "count": 1}
    ]


def test_host_shape_distinguishes_role():
    primary = host_shape([("server", "primary")])
    standby = host_shape([("server", "standby")])
    assert primary != standby


def test_host_shape_distinguishes_type():
    assert host_shape([("server", None)]) != host_shape([("cache", None)])


def test_host_shape_of_nothing_is_empty():
    assert host_shape([]) == []


def _side(*, mocked=False, version="1.0", shape=None):
    return {"is_mocked": mocked, "version": version, "host_shape": shape or []}


def test_a_subsystem_on_one_side_only_is_exactly_one_difference():
    """Not presence AND version AND mocked AND host_shape.

    The absent side has no version, no mocked flag and no hosts, so comparing
    them would report a missing subsystem as four differences and inflate every
    count in the summary. The natural implementation — compare each dimension,
    then add presence — gets this wrong.
    """
    assert difference_kinds("left_only", _side(), None) == ["presence"]
    assert difference_kinds("right_only", None, _side()) == ["presence"]


def test_identical_sides_have_no_differences():
    assert difference_kinds("both", _side(), _side()) == []


def test_mocked_difference_is_reported():
    assert difference_kinds("both", _side(mocked=True), _side(mocked=False)) == ["mocked"]


def test_version_difference_is_reported():
    assert difference_kinds("both", _side(version="1.0"), _side(version="2.0")) == ["version"]


def test_a_version_missing_on_both_sides_is_not_a_difference():
    assert difference_kinds("both", _side(version=None), _side(version=None)) == []


def test_a_version_missing_on_one_side_is_a_difference():
    assert difference_kinds("both", _side(version=None), _side(version="2.0")) == ["version"]


def test_host_shape_difference_is_reported():
    left = _side(shape=host_shape([("server", "primary")]))
    right = _side(shape=host_shape([("server", "primary"), ("server", "standby")]))
    assert difference_kinds("both", left, right) == ["host_shape"]


def test_several_differences_are_all_reported_in_a_stable_order():
    left = _side(mocked=True, version="1.0")
    right = _side(mocked=False, version="2.0")
    assert difference_kinds("both", left, right) == ["mocked", "version"]
