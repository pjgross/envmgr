"""How hard a booking's claim on an environment is.

Its own module, mirroring `app/core/booking_states.py`, because both
`booking_request_service` (which sets the level) and `contention_service`
(which reads it) need these and must not import each other.

SOFT vs HARD is NOT the same axis as `booking_request.exclusive_use_requested`.
Exclusive use asks "can anyone else be in here with me"; this asks "can I be
pushed out". A load test can legitimately need the environment to itself and
still be entirely movable.

B4 ADVISES: nothing in the codebase may refuse, transition or cancel a booking
on the strength of this value. It breaks a tie in `contention_service._decide`
and it is rendered. That is all it does.
"""

PROTECTION_SOFT = "soft"
PROTECTION_HARD = "hard"

PROTECTION_LEVELS = frozenset({PROTECTION_SOFT, PROTECTION_HARD})
