# backend/tests/test_release_closeout_service.py
"""Hyper-care state and close requirements, computed on read.

Day rule: the END of a hyper-care window is a day, compared through
`expiry_boundary` — 23:59 UTC on the end day is still `active`; 00:00 the
next day is `overdue`. `stable` wins over every date."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import release_closeout_service as svc

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _phase(start=None, end=None):
    return SimpleNamespace(id=1, name="HC", start_date=start, end_date=end)


def test_no_phase_is_none():
    assert svc.hypercare_state(None, None, NOW) == "none"


def test_declared_stable_wins_over_every_date():
    assert svc.hypercare_state(None, NOW, NOW) == "stable"
    assert svc.hypercare_state(_phase(NOW + timedelta(days=5), NOW + timedelta(days=9)), NOW, NOW) == "stable"


def test_start_after_today_is_planned():
    assert svc.hypercare_state(_phase(NOW + timedelta(days=1), NOW + timedelta(days=10)), None, NOW) == "planned"


def test_start_later_today_is_already_active():
    later_today = NOW.replace(hour=23)
    assert svc.hypercare_state(_phase(later_today, NOW + timedelta(days=10)), None, NOW) == "active"


def test_undated_phase_is_active():
    assert svc.hypercare_state(_phase(), None, NOW) == "active"


def test_end_day_is_still_active_until_midnight():
    end = NOW.replace(hour=0, minute=0)  # ends "today"
    assert svc.hypercare_state(_phase(NOW - timedelta(days=10), end), None, NOW.replace(hour=23, minute=59)) == "active"


def test_the_day_after_the_end_is_overdue():
    end = NOW - timedelta(days=1)
    assert svc.hypercare_state(_phase(NOW - timedelta(days=10), end), None, NOW.replace(hour=0, minute=0)) == "overdue"


def test_naive_sqlite_datetimes_are_normalised():
    end = (NOW - timedelta(days=1)).replace(tzinfo=None)
    assert svc.hypercare_state(_phase(None, end), None, NOW) == "overdue"


def _release(**kw):
    base = dict(handover_confirmed_at=None, operations_group_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_unmet_requirements_names_each_missing_thing():
    state = {"key": "completed", "is_closed": True,
             "requires_pir_complete": True, "requires_handover_confirmed": True}
    assert svc.unmet_requirements(state, None, _release()) == [svc.PIR_INCOMPLETE, svc.HANDOVER_UNCONFIRMED]
    draft = SimpleNamespace(status="draft")
    assert svc.unmet_requirements(state, draft, _release()) == [svc.PIR_INCOMPLETE, svc.HANDOVER_UNCONFIRMED]
    complete = SimpleNamespace(status="complete")
    assert svc.unmet_requirements(state, complete, _release(handover_confirmed_at=NOW)) == []


def test_a_closed_state_with_no_requirements_is_always_enterable():
    assert svc.unmet_requirements({"key": "done", "is_closed": True}, None, _release()) == []


def test_a_non_closed_state_has_no_requirements_even_if_flags_are_set():
    state = {"key": "mid", "is_closed": False, "requires_pir_complete": True}
    assert svc.unmet_requirements(state, None, _release()) == []
