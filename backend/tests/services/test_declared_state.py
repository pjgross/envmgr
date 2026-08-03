"""The value a detector parses into.

The scanner accumulates one of these per detector across every file that
detector claimed, so addition has to be total: losing warnings when two files
merge would silently drop a parser's complaint about a malformed block.
"""
from app.services.scanning.declared import (
    DeclaredEdge, DeclaredState, DeclaredSubsystem,
)


def test_states_add_by_concatenating_every_field():
    a = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")],
        edges=[DeclaredEdge("api", "db", 5432, "compose.yml")],
        warnings=["first"],
    )
    b = DeclaredState(
        subsystems=[DeclaredSubsystem("db", "database", "postgres", "other.yml")],
        edges=[],
        warnings=["second"],
    )

    total = a + b

    assert [s.name for s in total.subsystems] == ["api", "db"]
    assert [(e.from_name, e.to_name) for e in total.edges] == [("api", "db")]
    assert total.warnings == ["first", "second"]


def test_addition_does_not_mutate_either_operand():
    a = DeclaredState(subsystems=[DeclaredSubsystem("api", "web_service", None, "a.yml")])
    b = DeclaredState(subsystems=[DeclaredSubsystem("db", "database", None, "b.yml")])

    a + b

    assert len(a.subsystems) == 1
    assert len(b.subsystems) == 1


def test_an_empty_state_has_empty_collections_not_none():
    """Callers iterate these without checking; None would blow up mid-scan."""
    empty = DeclaredState()
    assert empty.subsystems == [] and empty.edges == [] and empty.warnings == []


def test_declared_entries_are_hashable_so_they_can_be_deduplicated():
    one = DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")
    same = DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")
    assert len({one, same}) == 1
