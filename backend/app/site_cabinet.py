from __future__ import annotations

import os
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.order import Order
from app.models.plan import Plan
from app.models.asset import Asset
from app.models.order_style import OrderStyle
from app.models.style import Style

from fastapi import Form, Response, status

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    sha256_hex,
    verify_password,
)
from app.models.session_token import UserSession

router = APIRouter(prefix="/cabinet", tags=["cabinet"], include_in_schema=False)

FILES_TTL_DAYS = int(os.getenv("FILES_TTL_DAYS", "30"))

# Включатель (чтобы потом можно было выключить без удаления кода)
CABINET_ENABLED = os.getenv("CABINET_ENABLED", "1") == "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _storage_root() -> Path:
    root = Path(os.getenv("LOCAL_STORAGE_DIR", "./data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:960px;margin:24px auto;padding:0 16px;}}
    a{{color:#5b21b6;text-decoration:none}}
    .muted{{color:#6b7280}}
    .card{{border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin:12px 0}}
    .row{{display:flex;gap:12px;flex-wrap:wrap}}
    .btn{{display:inline-block;background:#5b21b6;color:#fff;padding:10px 14px;border-radius:12px;border:0;cursor:pointer}}
    input,select{{padding:10px;border:1px solid #e5e7eb;border-radius:12px}}
    code{{background:#f3f4f6;padding:2px 6px;border-radius:8px}}
  </style>
</head>
<body>
  <div class="row" style="justify-content:space-between;align-items:center;">
    <div><a href="/cabinet/orders"><b>Кабинет</b></a></div>
    <div class="muted"><a href="/pricing">Тарифы</a> · <a href="/how">Как работает</a> · <a href="/contacts">Контакты</a></div>
  </div>
  <hr style="border:0;border-top:1px solid #e5e7eb;margin:16px 0">
  {body}
</body>
</html>"""
    return HTMLResponse(html)


def _ensure_enabled():
    if not CABINET_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
async def cabinet_root():
    _ensure_enabled()
    return RedirectResponse("/cabinet/orders", status_code=302)


@router.get("/orders")
async def cabinet_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    q = await db.execute(
        select(Order, Plan)
        .join(Plan, Plan.id == Order.plan_id)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
    )
    rows = q.all()

    pq = await db.execute(select(Plan).order_by(Plan.code.asc()))
    plans = pq.scalars().all()

    items_html = ""
    for o, p in rows:
        items_html += f"""
        <div class="card">
          <div><b>Заказ</b> <code>{o.id}</code></div>
          <div class="muted">Статус: <b>{o.status}</b> · План: {p.title} (<code>{p.code}</code>) · Цена: {o.price_rub} ₽</div>
          <div style="margin-top:10px"><a class="btn" href="/cabinet/orders/{o.id}">Открыть</a></div>
        </div>
        """

    plans_html = ""
    for p in plans:
        plans_html += f"""
        <option value="{p.code}">{p.title} ({p.code})</option>
        """

    body = f"""
    <h1>Мои заказы</h1>
    <p class="muted">Пользователь: <b>{user.email}</b></p>

    <div class="card">
      <h3 style="margin-top:0">Создать заказ (для тестов)</h3>
      <p class="muted">Создаёт заказ в БД. Оплату можно делать уже на /pricing (или позже добавим кнопку оплаты прямо тут).</p>
      <form method="post" action="/cabinet/orders/create">
        <select name="plan_code" required>{plans_html}</select>
        <button class="btn" type="submit">Создать заказ</button>
      </form>
    </div>

    {items_html if items_html else '<p class="muted">Пока нет заказов.</p>'}
    """
    return _page("Кабинет — Заказы", body)


@router.get("/login")
async def cabinet_login_page(error: str | None = None):
    _ensure_enabled()
    err = f"<p style='color:#b91c1c'><b>{error}</b></p>" if error else ""
    return _page("Вход — Кабинет", f"""
<h1>Вход</h1>
<p class="muted">Войдите, чтобы открыть кабинет.</p>
{err}
<form method="post" action="/cabinet/login">
  <p><input name="email" type="email" required placeholder="Email" style="width:320px"></p>
  <p><input name="password" type="password" required placeholder="Пароль" style="width:320px"></p>
  <p><button class="btn" type="submit">Войти</button></p>
</form>
<p class="muted">Если email не подтверждён — сначала подтвердите его (пока через API).</p>
""")


@router.post("/login")
async def cabinet_login_submit(
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    email_norm = str(email).lower().strip()

    q = await db.execute(select(User).where(User.email == email_norm))
    user = q.scalar_one_or_none()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return RedirectResponse("/cabinet/login?error=Неверный+логин+или+пароль", status_code=302)

    if not user.email_verified_at:
        return RedirectResponse("/cabinet/login?error=Email+не+подтверждён", status_code=302)

    access = create_access_token(sub=str(user.id))
    refresh = create_refresh_token(sub=str(user.id))

    sess = UserSession(
        user_id=user.id,
        refresh_token_hash=sha256_hex(refresh),
        expires_at=_now() + timedelta(days=settings.refresh_token_days),
    )
    db.add(sess)

    user.last_login_at = _now()
    await db.commit()

    resp = RedirectResponse("/cabinet/orders", status_code=302)

    secure_cookie = settings.env == "prod"
    resp.set_cookie(
        "access_token",
        access,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=60 * settings.access_token_minutes,
    )
    resp.set_cookie(
        "refresh_token",
        refresh,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=60 * 60 * 24 * settings.refresh_token_days,
    )
    return resp


@router.post("/logout")
async def cabinet_logout():
    _ensure_enabled()
    resp = RedirectResponse("/cabinet/login", status_code=302)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


@router.post("/orders/create")
async def cabinet_create_order(
    plan_code: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    pq = await db.execute(select(Plan).where(Plan.code == plan_code))
    plan = pq.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=400, detail="Unknown plan_code")

    now = _now()
    order = Order(
        user_id=user.id,
        plan_id=plan.id,
        status="paid",  # для тестов: считаем оплаченным (чтобы проходить пайплайн)
        price_rub=0,
        cost_estimate_rub=0,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.get("/orders/{order_id}")
async def cabinet_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    oq = await db.execute(select(Order, Plan).join(Plan, Plan.id == Order.plan_id).where(Order.id == order_id, Order.user_id == user.id))
    row = oq.first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    order, plan = row

    aq = await db.execute(select(Asset).where(Asset.order_id == order.id, Asset.user_id == user.id).order_by(Asset.created_at.asc()))
    assets = aq.scalars().all()

    sq = await db.execute(select(OrderStyle).where(OrderStyle.order_id == order.id).order_by(OrderStyle.created_at.asc()))
    selected_styles = [s.style_code for s in sq.scalars().all()]

    stq = await db.execute(
        select(Style)
        .where(Style.is_active.is_(True))
        .order_by(Style.weight.asc(), Style.created_at.asc())
    )
    styles = stq.scalars().all()

    styles_checkboxes = ""
    for s in styles:
        checked = "checked" if s.code in selected_styles else ""
        styles_checkboxes += f"""
        <label style="display:block;margin:6px 0">
          <input type="checkbox" name="style_codes" value="{s.code}" {checked}>
          <b>{s.name}</b> <span class="muted">({s.code})</span>
        </label>
        """

    assets_html = ""
    for a in assets:
        assets_html += f"""
        <div class="card">
          <div><b>{a.kind}</b> · {a.filename or '<без имени>'}</div>
          <div class="muted">id: <code>{a.id}</code> · {a.content_type} · {a.size_bytes or '-'} bytes</div>
          <div class="muted">storage: {a.storage_driver}:{a.storage_key}</div>
        </div>
        """
    if not assets_html:
        assets_html = "<p class='muted'>Пока нет файлов.</p>"

    body = f"""
    <h1>Заказ</h1>
    <p class="muted">
      id: <code>{order.id}</code><br>
      статус: <b>{order.status}</b><br>
      план: {plan.title} (<code>{plan.code}</code>)
    </p>

    <div class="card">
      <h3 style="margin-top:0">Шаг 1 — Фото-профиль (загрузка)</h3>
      <form method="post" action="/cabinet/orders/{order.id}/face-profile" enctype="multipart/form-data">
        <input type="file" name="files" multiple required accept="image/*">
        <button class="btn" type="submit">Загрузить фото</button>
      </form>
      <p class="muted">После загрузки поставим статус <code>awaiting_styles</code>.</p>
    </div>

    <div class="card">
      <h3 style="margin-top:0">Шаг 2 — Выбор стилей</h3>
      <form method="post" action="/cabinet/orders/{order.id}/styles">
        {styles_checkboxes}
        <button class="btn" type="submit">Сохранить стили</button>
      </form>
      <p class="muted">После выбора поставим статус <code>awaiting_image_generation</code>.</p>
    </div>

    <h2>Файлы заказа</h2>
    {assets_html}
    """
    return _page("Кабинет — Заказ", body)


@router.post("/orders/{order_id}/face-profile")
async def cabinet_upload_face_profile(
    order_id: str,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    oq = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    root = _storage_root()
    now = _now()

    created_any = False
    for f in files:
        data = await f.read()
        if not data:
            continue
        created_any = True

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
            delete_after=now + timedelta(days=FILES_TTL_DAYS),
        )
        db.add(a)

    if not created_any:
        raise HTTPException(status_code=400, detail="All uploaded files were empty")

    order.status = "awaiting_styles"
    order.updated_at = now
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.post("/orders/{order_id}/styles")
async def cabinet_select_styles(
    order_id: str,
    style_codes: list[str] = Form([]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    if not style_codes:
        raise HTTPException(status_code=400, detail="Choose at least one style")

    oq = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # проверяем что стили существуют
    sq = await db.execute(select(Style.code).where(Style.code.in_(style_codes), Style.is_active.is_(True)))
    found = set(sq.scalars().all())
    missing = [c for c in style_codes if c not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown/inactive styles: {missing}")

    await db.execute(delete(OrderStyle).where(OrderStyle.order_id == order.id))
    for code in dict.fromkeys(style_codes):
        db.add(OrderStyle(order_id=order.id, style_code=code))

    order.status = "awaiting_image_generation"
    order.updated_at = _now()
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)
