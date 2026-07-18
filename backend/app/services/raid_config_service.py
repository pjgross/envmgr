"""Per-tenant RAID scoring config: probability/impact scales + RAG bands."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.raid import RaidConfig

DEFAULT_RAID_CONFIG = {
    "probability_scale": [
        {"level": 1, "label": "Rare", "color": "#4caf50"},
        {"level": 2, "label": "Unlikely", "color": "#8bc34a"},
        {"level": 3, "label": "Possible", "color": "#ffc107"},
        {"level": 4, "label": "Likely", "color": "#ff9800"},
        {"level": 5, "label": "Almost certain", "color": "#f44336"},
    ],
    "impact_scale": [
        {"level": 1, "label": "Negligible", "color": "#4caf50"},
        {"level": 2, "label": "Minor", "color": "#8bc34a"},
        {"level": 3, "label": "Moderate", "color": "#ffc107"},
        {"level": 4, "label": "Major", "color": "#ff9800"},
        {"level": 5, "label": "Severe", "color": "#f44336"},
    ],
    "rag_bands": [
        {"rag": "green", "min": 1, "max": 5, "color": "#4caf50"},
        {"rag": "amber", "min": 6, "max": 14, "color": "#ff9800"},
        {"rag": "red", "min": 15, "max": 25, "color": "#f44336"},
    ],
}


async def seed_default_config(db: AsyncSession, tenant_id: int) -> RaidConfig:
    """Insert the default config for a tenant if none exists; return the row."""
    existing = (
        await db.execute(select(RaidConfig).where(RaidConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    cfg = RaidConfig(
        tenant_id=tenant_id,
        probability_scale=list(DEFAULT_RAID_CONFIG["probability_scale"]),
        impact_scale=list(DEFAULT_RAID_CONFIG["impact_scale"]),
        rag_bands=list(DEFAULT_RAID_CONFIG["rag_bands"]),
    )
    db.add(cfg)
    await db.flush()
    return cfg


async def get_or_seed_config(db: AsyncSession, tenant_id: int) -> RaidConfig:
    return await seed_default_config(db, tenant_id)


async def update_config(
    db: AsyncSession,
    tenant_id: int,
    *,
    probability_scale: Optional[list] = None,
    impact_scale: Optional[list] = None,
    rag_bands: Optional[list] = None,
) -> RaidConfig:
    cfg = await get_or_seed_config(db, tenant_id)
    if probability_scale is not None:
        cfg.probability_scale = probability_scale
    if impact_scale is not None:
        cfg.impact_scale = impact_scale
    if rag_bands is not None:
        cfg.rag_bands = rag_bands
    await db.flush()
    return cfg
