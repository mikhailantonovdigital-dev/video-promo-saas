from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User
from app.services.yookassa_client import YooKassaClient

router = APIRouter(prefix="/checkout", tags=["checkout"])


def _ensure_yookassa_configured() -> None:
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key or not settings.yookassa_return_url:
        raise HTTPException(status_code=500, detail="YOOKASSA_* env vars are missing")


def _ensure_pricing_configured() -> None:
    if settings.cost_image_rub is None or settings.cost_video_rub is None or settings.cost_training_rub is None:
        raise HTTPException(status_code=500, detail="Pricing is not configured (COST_* env vars are missing)")


@router.post("")
async def create_checkout(
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _ensure_yookassa_configured()
    _ensure_pricing_configured()

    plan_code = str(payload.get("plan_code") or "").strip()
    if not plan_code:
        raise HTTPException(status_code=400, detail="plan_code is required")

    q = await db.execute(select(Plan).where(Plan.code == plan_code, Plan.is_active == True))
    plan = q.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Пока считаем, что обучение нужно (в следующем этапе привяжем к identity_profile)
    cost = plan.images_count * settings.cost_image_rub + plan.videos_count * settings.cost_video_rub + settings.cost_training_rub
    price = int(math.ceil(cost * settings.min_price_multiplier))

    order = Order(
        user_id=user.id,
        plan_id=plan.id,
        status="payment_pending",
        currency="RUB",
        price_rub=price,
        cost_estimate_rub=int(math.ceil(cost)),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    client = YooKassaClient(
        api_base=settings.yookassa_api_base,
        shop_id=settings.yookassa_shop_id,
        secret_key=settings.yookassa_secret_key,
    )

    yk = await client.create_payment(
        amount_rub=price,
        return_url=settings.yookassa_return_url,
        description=f"Video Promo SaaS order {order.id}",
        idempotence_key=str(order.id),
        metadata={"order_id": str(order.id), "user_id": str(user.id), "plan_code": plan.code},
    )

    yk_id = yk.get("id")
    confirmation_url = (yk.get("confirmation") or {}).get("confirmation_url")
    status = yk.get("status") or "pending"

    if not yk_id:
        raise HTTPException(status_code=502, detail="YooKassa: no payment id")

    pay = Payment(
        order_id=order.id,
        provider="yookassa",
        provider_payment_id=yk_id,
        status=status,
        amount_rub=price,
        confirmation_url=confirmation_url,
    )
    db.add(pay)
    await db.commit()

    return {"order_id": str(order.id), "payment_id": yk_id, "confirmation_url": confirmation_url}
