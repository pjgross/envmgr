"""Smoke test for the ApiKey model — shape + column nullability."""
from app.db.models.api_key import ApiKey


def test_api_key_model_columns():
    cols = {c.name: c for c in ApiKey.__table__.columns}
    assert "key_hash" in cols
    assert cols["key_hash"].nullable is False
    assert "name" in cols
    assert cols["scopes"].nullable is False
    assert cols["created_by"].nullable is False
    assert cols["last_used_at"].nullable is True
    assert cols["expires_at"].nullable is True
    assert cols["tenant_id"].nullable is False
    assert cols["deleted_at"].nullable is True
