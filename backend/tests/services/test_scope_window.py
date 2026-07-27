from datetime import datetime, timedelta, timezone

from app.services.scope_window import compute_scope_window

NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def test_shipped_when_actual_date_set():
    # actual_date wins even if a deadline exists and is in the past
    status, days = compute_scope_window(NOW - timedelta(days=5), NOW - timedelta(days=1), NOW)
    assert status == "shipped"
    assert days is None


def test_no_cutoff_when_no_deadline():
    status, days = compute_scope_window(None, None, NOW)
    assert status == "no_cutoff"
    assert days is None


def test_closed_when_deadline_passed():
    status, days = compute_scope_window(NOW - timedelta(days=2), None, NOW)
    assert status == "closed"
    assert days == -2


def test_closing_soon_within_threshold():
    status, days = compute_scope_window(NOW + timedelta(days=3), None, NOW)
    assert status == "closing_soon"
    assert days == 3


def test_closing_soon_at_exactly_seven_days():
    status, days = compute_scope_window(NOW + timedelta(days=7), None, NOW)
    assert status == "closing_soon"
    assert days == 7


def test_open_when_comfortably_ahead():
    status, days = compute_scope_window(NOW + timedelta(days=30), None, NOW)
    assert status == "open"
    assert days == 30


def test_naive_deadline_treated_as_utc():
    naive = (NOW + timedelta(days=10)).replace(tzinfo=None)
    status, days = compute_scope_window(naive, None, NOW)
    assert status == "open"
    assert days == 10
