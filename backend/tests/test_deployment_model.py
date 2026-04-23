"""Smoke test for the Deployment model — required + nullable columns."""
from app.db.models.deployment import Deployment


def test_deployment_model_columns():
    cols = {c.name: c for c in Deployment.__table__.columns}
    for required in ("build_id", "environment_id", "change_request_id",
                     "event_id", "deployed_at", "status", "tenant_id"):
        assert required in cols, required
        assert cols[required].nullable is False, required
    for optional in ("release_id", "deployer_name", "completed_at"):
        assert cols[optional].nullable is True, optional
    assert "custom_fields" in cols
