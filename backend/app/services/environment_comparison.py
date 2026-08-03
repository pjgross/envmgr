"""Pure comparison logic for environment diffs — no database access.

Kept separate from the service so the rules that decide what counts as a
difference can be tested exhaustively without fixtures.
"""
from collections import Counter
from typing import Optional

# Order is fixed so `differences` arrays compare equal regardless of how they
# were built, and so the UI can render chips in a stable order.
_KIND_ORDER = ("mocked", "version", "host_shape")


def host_shape(attachments: list[tuple[str, Optional[str]]]) -> list[dict]:
    """Normalise a subsystem's host attachments into a comparable shape.

    `attachments` is (component_type, role) per host. Host *names* differ
    between environments by design, so identity is never compared — what
    matters is how many hosts of what type and role a subsystem runs on.

    Sorted, so equality is a plain structural comparison rather than a set
    intersection. `role` is nullable, hence the `or ""` in the sort key.
    """
    counts = Counter(attachments)
    return sorted(
        (
            {"component_type": component_type, "role": role, "count": count}
            for (component_type, role), count in counts.items()
        ),
        key=lambda entry: (entry["component_type"], entry["role"] or ""),
    )


def difference_kinds(
    presence: str, left: Optional[dict], right: Optional[dict]
) -> list[str]:
    """Which dimensions differ between the two sides.

    A subsystem present on only one side is exactly one difference —
    "presence" — and never also a version/mocked/host difference. The absent
    side has no values to compare, so reporting four differences for one
    missing subsystem would inflate every count in the summary.
    """
    if presence != "both":
        return ["presence"]

    assert left is not None and right is not None
    differing = {
        "mocked": left["is_mocked"] != right["is_mocked"],
        # None == None is not a difference: a subsystem nobody has recorded a
        # version for on either side is consistent, not divergent.
        "version": left["version"] != right["version"],
        "host_shape": left["host_shape"] != right["host_shape"],
    }
    return [kind for kind in _KIND_ORDER if differing[kind]]
