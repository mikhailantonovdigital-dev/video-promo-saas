from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.user import User
from app.models.order import Order
from app.models.payment import Payment
from app.models.plan import Plan

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", dependencies=[Depends(require_admin)])
async def admin_users(limit: int = 50, offset: int = 0, q: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    stmt = select(User).order_by(desc(User.created_at)).limit(limit).offset(offset)
    if q:
        stmt = select(User).where(User.email.ilike(f"%{q.lower()}%")).order_by(desc(User.created_at)).limit(limit).offset(offset)

    res = await db.execute(stmt)
    items = res.scalars().all()
    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "email_verified": bool(u.email_verified_at),
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
            }
            for u in items
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/orders", dependencies=[Depends(require_admin)])
async def admin_orders(limit: int = 50, offset: int = 0, status: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    stmt = (
        select(Order, User, Plan)
        .join(User, User.id == Order.user_id)
        .join(Plan, Plan.id == Order.plan_id)
        .order_by(desc(Order.created_at))
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(Order.status == status)

    res = await db.execute(stmt)
    rows = res.all()

    return {
        "items": [
            {
                "order_id": str(o.id),
                "status": o.status,
                "price_rub": o.price_rub,
                "cost_estimate_rub": o.cost_estimate_rub,
                "created_at": o.created_at,
                "updated_at": o.updated_at,
                "user": {"id": str(u.id), "email": u.email},
                "plan": {"code": p.code, "title": p.title, "videos_count": p.videos_count, "images_count": p.images_count},
            }
            for (o, u, p) in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/payments", dependencies=[Depends(require_admin)])
async def admin_payments(limit: int = 50, offset: int = 0, status: str | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    stmt = select(Payment).order_by(desc(Payment.created_at)).limit(limit).offset(offset)
    if status:
        stmt = select(Payment).where(Payment.status == status).order_by(desc(Payment.created_at)).limit(limit).offset(offset)

    res = await db.execute(stmt)
    items = res.scalars().all()

    return {
        "items": [
            {
                "id": str(p.id),
                "order_id": str(p.order_id),
                "provider": p.provider,
                "provider_payment_id": p.provider_payment_id,
                "status": p.status,
                "amount_rub": p.amount_rub,
                "created_at": p.created_at,
                "paid_at": p.paid_at,
            }
            for p in items
        ],
        "limit": limit,
        "offset": offset,
    }
