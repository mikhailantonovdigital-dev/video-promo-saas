from __future__ import annotations

import os
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.order import Order
from app.models.plan import Plan
from app.models.style import Style
from app.models.user import User
from app.models.asset import Asset
from app.models.order_style import OrderStyle

router = APIRouter(prefix="/orders", tags=["orders"])

FILES_TTL_DAYS = int(os.getenv("FILES_TTL_DAYS", "30"))
FACE_PROFILE_TTL_DAYS = int(os.getenv("FACE_PROFILE_TTL_DAYS", "365"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid UUID")


def _storage_root() -> Path:
    # В Render лучше потом подключить диск или S3, но для MVP норм
    root = Path(os.getenv("LOCAL_STORAGE_DIR", "./data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.get("")
async def list_my_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = await db.execute(
        select(Order, Plan)
        .join(Plan, Plan.id == Order.plan_id)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
    )
    rows = q.all()
    return {
        "items": [
            {
                "order_id": str(o.id),
                "status": o.status,
                "price_rub": o.price_rub,
                "created_at": o.created_at,
                "plan": {"code": p.code, "title": p.title, "videos_count": p.videos_count, "images_count": p.images_count},
            }
            for (o, p) in rows
        ]
    }


@router.get("/{order_id}")
async def get_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    oid = _uuid(order_id)

    oq = await db.execute(
        select(Order, Plan)
        .join(Plan, Plan.id == Order.plan_id)
        .where(Order.id == oid, Order.user_id == user.id)
    )
    row = oq.first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    order, plan = row

    aq = await db.execute(select(Asset).where(Asset.order_id == oid, Asset.user_id == user.id).order_by(Asset.created_at.asc()))
    assets = aq.scalars().all()

    sq = await db.execute(select(OrderStyle).where(OrderStyle.order_id == oid).order_by(OrderStyle.created_at.asc()))
    styles = [s.style_code for s in sq.scalars().all()]

    return {
        "order_id": str(order.id),
        "status": order.status,
        "price_rub": order.price_rub,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "plan": {"code": plan.code, "title": plan.title, "videos_count": plan.videos_count, "images_count": plan.images_count},
        "styles": styles,
        "assets": [
            {
                "id": str(a.id),
                "kind": a.kind,
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "storage_driver": a.storage_driver,
                "storage_key": a.storage_key,
                "delete_after": a.delete_after,
                "created_at": a.created_at,
            }
            for a in assets
        ],
    }


@router.post("/{order_id}/face-profile")
async def upload_face_profile(
    order_id: str,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Шаг ТЗ: "фото-профиль".
    Загружаем 1..N фото, сохраняем как assets(kind=profile_photo).
    """
    oid = _uuid(order_id)

    oq = await db.execute(select(Order).where(Order.id == oid, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in {"paid", "awaiting_face_profile", "awaiting_styles"}:
        raise HTTPException(status_code=409, detail=f"Order status does not allow face upload: {order.status}")

    if not files:
        raise HTTPException(status_code=400, detail="No files")

    root = _storage_root()
    now = _now()
    created = []

    for f in files:
        data = await f.read()
        if not data:
            continue

        sha = hashlib.sha256(data).hexdigest()
        safe_name = (f.filename or "photo.jpg").replace("/", "_").replace("\\", "_")

        rel = Path("uploads") / "u" / str(user.id) / "o" / str(order.id) / "profile" / f"{uuid.uuid4().hex}_{safe_name}"
        abs_path = root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

        a = Asset(
            user_id=user.id,
            order_id=order.id,
            kind="profile_photo",
            storage_driver="local",
            storage_key=str(rel),
            filename=safe_name,
            content_type=f.content_type or "application/octet-stream",
            size_bytes=len(data),
            sha256=sha,
            # Лицо/фото-профиль храним 12 месяцев (можно переопределить env FACE_PROFILE_TTL_DAYS)
            delete_after=now + timedelta(days=FACE_PROFILE_TTL_DAYS),
        )
        db.add(a)
        await db.flush()
        created.append({"asset_id": str(a.id), "filename": a.filename})

    if not created:
        raise HTTPException(status_code=400, detail="All uploaded files were empty")

    # После первой загрузки фото — можно переходить к выбору стилей
    order.status = "awaiting_styles"
    order.updated_at = now

    await db.commit()
    return {"ok": True, "order_id": str(order.id), "next_status": order.status, "created": created}


@router.post("/{order_id}/styles")
async def select_styles(
    order_id: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Шаг ТЗ: "выбор стилей".
    body: {"style_codes":["cinematic","neon",...]}
    """
    oid = _uuid(order_id)
    style_codes = payload.get("style_codes")

    if not isinstance(style_codes, list) or not style_codes:
        raise HTTPException(status_code=400, detail="style_codes must be a non-empty list")

    style_codes = [str(x).strip() for x in style_codes if str(x).strip()]
    style_codes = list(dict.fromkeys(style_codes))
    if len(style_codes) > 5:
        raise HTTPException(status_code=400, detail="Max 5 styles per order (MVP)")

    oq = await db.execute(select(Order).where(Order.id == oid, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in {"awaiting_styles"}:
        raise HTTPException(status_code=409, detail=f"Order status does not allow styles selection: {order.status}")

    # Проверяем, что стили существуют и активны
    sq = await db.execute(select(Style.code).where(Style.code.in_(style_codes), Style.is_active.is_(True)))
    found = set(sq.scalars().all())
    missing = [c for c in style_codes if c not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown/inactive styles: {missing}")

    # Перезаписываем список выбранных стилей
    await db.execute(delete(OrderStyle).where(OrderStyle.order_id == order.id))
    for code in style_codes:
        db.add(OrderStyle(order_id=order.id, style_code=code))

    order.status = "awaiting_image_generation"
    order.updated_at = _now()

    await db.commit()
    return {"ok": True, "order_id": str(order.id), "next_status": order.status, "styles": style_codes}
