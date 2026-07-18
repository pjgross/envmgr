"""Tests for raid_service scoring + status-transition helpers (pure functions)."""
from app.services import raid_service
from app.services.raid_config_service import DEFAULT_RAID_CONFIG


def test_severity_multiplies():
    assert raid_service.severity(4, 5) == 20
    assert raid_service.severity(1, 1) == 1


def test_severity_none_when_factor_missing():
    assert raid_service.severity(None, 5) is None
    assert raid_service.severity(3, None) is None


def test_rag_bands():
    assert raid_service.rag(3, DEFAULT_RAID_CONFIG) == "green"    # 1..5
    assert raid_service.rag(10, DEFAULT_RAID_CONFIG) == "amber"   # 6..14
    assert raid_service.rag(20, DEFAULT_RAID_CONFIG) == "red"     # 15..25
    assert raid_service.rag(None, DEFAULT_RAID_CONFIG) is None


def test_transition_allowed():
    assert raid_service.is_transition_allowed("risk", "open", "mitigating") is True
    assert raid_service.is_transition_allowed("risk", "mitigating", "closed") is True
    assert raid_service.is_transition_allowed("risk", "open", "resolved") is False
    assert raid_service.is_transition_allowed("issue", "open", "in_progress") is True
    assert raid_service.is_transition_allowed("issue", "resolved", "closed") is True
    assert raid_service.is_transition_allowed("dependency", "identified", "met") is False  # must pass in_progress
    assert raid_service.is_transition_allowed("dependency", "in_progress", "met") is True
    # same-state is a no-op, allowed
    assert raid_service.is_transition_allowed("issue", "open", "open") is True
