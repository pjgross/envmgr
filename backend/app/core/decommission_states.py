"""B5 — the five decommission states.

Its own module, mirroring app/core/booking_states.py and
app/core/protection_levels.py, so the service, the API schemas and the tests
share one vocabulary without importing each other.

THESE ARE COMPUTED, NEVER STORED. There is no `state` column on
environment_decommission and there must never be one — see the spec §4.2.
"""

STATE_WARNED = "warned"
STATE_DUE = "due"
STATE_EXTENSION_REQUESTED = "extension_requested"
STATE_TORN_DOWN = "torn_down"
STATE_CANCELLED = "cancelled"

DECOMMISSION_STATES = (
    STATE_WARNED,
    STATE_DUE,
    STATE_EXTENSION_REQUESTED,
    STATE_TORN_DOWN,
    STATE_CANCELLED,
)

# Deliberately NO `LIVE_STATES` tuple. 'Live' is decided by
# `environment_decommission_service.live_predicate`, in SQL, over the same
# three columns -- a parallel tuple here would be a second definition of one
# rule, and the two would drift the first time a state is added.
