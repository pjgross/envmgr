"""Which booking statuses count as a live claim on an environment.

This set was already duplicated in environment_health_service and
environment_utilization_service. The third consumer (reserved_now) is the point
at which it becomes one constant rather than three copies that can drift.

Deliberately NOT the same as conflict_service.TERMINAL_STATES ({rejected,
closed}): that one counts drafts *as* conflicts, which is a different question.
Do not merge them.
"""

# draft is uncommitted; rejected and closed are terminal.
INACTIVE_BOOKING_STATUSES = frozenset({"draft", "rejected", "closed"})
