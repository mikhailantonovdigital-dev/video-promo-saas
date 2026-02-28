from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.order import Order
from app.models.order_style import OrderStyle
from app.models.plan import Plan
from app.models.prompt_history import PromptHistory
from app.models.video_job import VideoJob


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _video_prompt(style_codes: list[str], idx: int) -> str:
    styles = ", ".join(style_codes[:5]) if style_codes else "default"
    # без длинного тире
    return (
        f"Vertical short promo video for a music track. "
        f"Style: {styles}. "
        f"Shot #{idx + 1}. "
        f"No text overlay, no watermark, no logos."
    )


def _prompt_hash(prompt_text: str, *, order_id: str, idx: int) -> str:
    # хэш солим order_id+idx, чтобы один и тот же текст в разных заказах НЕ конфликтовал
    raw = f"{prompt_text}\norder:{order_id}\nidx:{idx}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def ensure_video_jobs_for_order(db: AsyncSession, order: Order) -> int:
    """Создаёт video_jobs для заказа (если ещё не созданы). Возвращает сколько создано."""

    q = await db.execute(select(func.count(VideoJob.id)).where(VideoJob.order_id == order.id))
    existing = int(q.scalar() or 0)
    if existing > 0:
        return 0

    plan = await db.get(Plan, order.plan_id)
    if not plan:
        raise ValueError("Plan not found")

    aq = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == order.user_id,
            Asset.kind.in_(["selected_image", "profile_photo"]),
        )
    )
    assets = aq.scalars().all()

    # Для Kling нужен реальный доступный URL, поэтому используем только local assets.
    selected_images = [a for a in assets if a.kind == "selected_image" and a.storage_driver == "local"]
    if not selected_images:
        selected_images = [a for a in assets if a.kind == "profile_photo" and a.storage_driver == "local"]

    vq = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == order.user_id,
            Asset.kind == "video_ref",
        )
    )
    video_refs = vq.scalars().all()

    if not selected_images:
        raise ValueError("No selected_image (or profile_photo) found for order")
    if not video_refs:
        raise ValueError("No video_ref found for order")

    sq = await db.execute(select(OrderStyle.style_code).where(OrderStyle.order_id == order.id))
    style_codes = [r[0] for r in sq.all()]

    now = _now()

    created = 0
    for i in range(int(plan.videos_count)):
        prompt_text = _video_prompt(style_codes=style_codes, idx=i)
        prompt_hash = _prompt_hash(prompt_text, order_id=str(order.id), idx=i)

        db.add(
            PromptHistory(
                user_id=order.user_id,
                prompt_hash=prompt_hash,
                prompt_text=prompt_text,
                created_at=now,
            )
        )

        db.add(
            VideoJob(
                user_id=order.user_id,
                order_id=order.id,
                idx=i,
                provider="kling",
                status="queued",
                image_asset_id=selected_images[i % len(selected_images)].id,
                video_ref_asset_id=video_refs[i % len(video_refs)].id,
                prompt_hash=prompt_hash,
                attempts=0,
                next_poll_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        created += 1

    # Не коммитим здесь: вызывающий сам управляет транзакцией.
    await db.flush()
    return created
