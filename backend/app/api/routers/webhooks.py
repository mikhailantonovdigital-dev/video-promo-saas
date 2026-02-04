from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment
from app.services.yookassa_client import YooKassaClient

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/yookassa")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await request.json()

    event = payload.get("event")
    obj = payload.get("object") or {}
    payment_id = obj.get("id")

    if not payment_id:
        raise HTTPException(status_code=400, detail="No payment id")

    # Доп. защита: подтверждаем статус платежа запросом в ЮKassa (без этого вебхук сложнее доверять)
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise HTTPException(status_code=500, detail="YOOKASSA_* env vars are missing")

    client = YooKassaClient(
        api_base=settings.yookassa_api_base,
        shop_id=settings.yookassa_shop_id,
        secret_key=settings.yookassa_secret_key,
    )
    verified = await client.get_payment(payment_id=payment_id)
    verified_status = verified.get("status")

    q = await db.execute(select(Payment).where(Payment.provider_payment_id == payment_id))
    pay = q.scalar_one_or_none()
    if not pay:
        # webhook мог прийти раньше записи, но у нас это маловероятно; пока просто 200
        return {"ok": True}

    pay.raw_webhook = payload
    pay.status = verified_status or pay.status

    oq = await db.execute(select(Order).where(Order.id == pay.order_id))
    order = oq.scalar_one_or_none()
    if order:
        if verified_status == "succeeded":
            pay.paid_at = datetime.now(timezone.utc)
            order.status = "paid"
            order.updated_at = datetime.now(timezone.utc)
        elif verified_status in {"canceled"}:
            order.status = "canceled"
            order.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return {"ok": True, "event": event, "status": verified_status}
