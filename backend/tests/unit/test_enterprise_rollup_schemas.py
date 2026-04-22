from app.api.v1.schemas.enterprise_rollup import (
    SystemRollupRow,
    ScopeRollupFilters,
    TimelineRollupRead,
    MemberStateCount,
    EnterpriseReportRead,
)


def test_system_rollup_row_shape():
    r = SystemRollupRow(
        system_id=1,
        system_name="orders-api",
        roles_by_project={"proj-A": ["changing"], "proj-B": ["regression"]},
    )
    assert r.system_id == 1


def test_scope_rollup_filters_default_empty():
    f = ScopeRollupFilters()
    assert f.change_kind is None
    assert f.status is None


def test_member_state_count():
    m = MemberStateCount(state="in_progress", count=2, projects=["Alpha", "Beta"])
    assert m.count == 2


def test_report_read_has_all_sections():
    r = EnterpriseReportRead(
        enterprise_id=1,
        name="R1",
        status="integration_testing",
        target_date=None,
        actual_date=None,
        description=None,
        members=[],
        systems=[],
        scope_by_project={},
        events=[],
        dependencies=[],
        generated_at="2026-04-22T00:00:00Z",
        generated_by="user",
    )
    assert r.enterprise_id == 1
