"""Smoke test for the Build model — required columns + nullability."""
from app.db.models.build import Build


def test_build_model_columns():
    cols = {c.name: c for c in Build.__table__.columns}
    for required in ("subsystem_id", "git_sha", "commit_timestamp", "tenant_id"):
        assert required in cols, required
        assert cols[required].nullable is False, required
    for optional in ("release_id", "git_branch", "build_number",
                     "build_started_at", "build_finished_at"):
        assert cols[optional].nullable is True, optional
    for jsonish in ("jira_tickets", "pipeline_steps", "custom_fields"):
        assert jsonish in cols, jsonish
