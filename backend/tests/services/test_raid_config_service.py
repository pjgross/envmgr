"""Tests for raid_config_service — per-tenant RAID scoring config."""
import pytest

from app.services import raid_config_service


@pytest.mark.asyncio
async def test_get_or_seed_config_seeds_defaults(db_session, tenant):
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    assert len(cfg.probability_scale) == 5
    assert len(cfg.impact_scale) == 5
    assert len(cfg.rag_bands) == 3
    # idempotent — second call returns the same row, does not duplicate
    cfg2 = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    assert cfg2.id == cfg.id


@pytest.mark.asyncio
async def test_update_config_persists(db_session, tenant):
    new_bands = [
        {"rag": "green", "min": 1, "max": 3, "color": "#0f0"},
        {"rag": "red", "min": 4, "max": 25, "color": "#f00"},
    ]
    cfg = await raid_config_service.update_config(db_session, tenant.id, rag_bands=new_bands)
    assert cfg.rag_bands == new_bands
    # unchanged fields keep their seeded defaults
    assert len(cfg.probability_scale) == 5
