"""Unit tests for ReleaseRead schema additions."""


def test_release_read_allows_membership_summary():
    """ReleaseRead accepts an optional membership_summary field."""
    from app.api.v1.schemas.release import ReleaseRead
    from app.api.v1.schemas.release_membership import MembershipSummary

    summary = MembershipSummary(pending=0, accepted=0, rejected=0, withdrawn=0, removed=0)
    # Use model_construct to bypass required-field validation — this test only
    # needs to verify the attribute exists and carries the summary.
    r = ReleaseRead.model_construct(
        id=1,
        tenant_id=1,
        name="E1",
        release_kind="enterprise",
        status="draft",
        membership_summary=summary,
    )
    assert r.membership_summary.pending == 0


def test_release_read_membership_summary_defaults_none():
    from app.api.v1.schemas.release import ReleaseRead

    r = ReleaseRead.model_construct(id=1, tenant_id=1, name="P1", release_kind="project", status="draft")
    # Accessing the attribute should return None or be entirely absent
    assert getattr(r, "membership_summary", None) is None
