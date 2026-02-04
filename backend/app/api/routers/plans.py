from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.api.deps import get_db
from app.core.config import settings
from app.models.plan import Plan

router = APIRouter(prefix="/plans", tags=["plans"])


def _ensure_pricing_configured() -> None:
    if settings.cost_image_rub is None or settings.cost_video_rub is None or settings.cost_training_rub is None:
        raise HTTPException(status_code=500, detail="Pricing is not configured (COST_* env vars are missing)")


@router.get("")
async def list_plans(db: AsyncSession = Depends(get_db)) -> list[dict]:
    _ensure_pricing_configured()

    q = await db.execute(select(Plan).where(Plan.is_active == True).order_by(Plan.videos_count.asc()))
    plans = q.scalars().all()

    out: list[dict] = []
    for p in plans:
        cost_first = p.images_count * settings.cost_image_rub + p.videos_count * settings.cost_video_rub + settings.cost_training_rub
        cost_repeat = p.images_count * settings.cost_image_rub + p.videos_count * settings.cost_video_rub

        price_first = int(math.ceil(cost_first * settings.min_price_multiplier))
        price_repeat = int(math.ceil(cost_repeat * settings.min_price_multiplier))

        out.append(
            {
                "code": p.code,
                "title": p.title,
                "images_count": p.images_count,
                "videos_count": p.videos_count,
                "price_rub_first_order": price_first,
                "price_rub_repeat_order": price_repeat,
            }
        )
    return out
