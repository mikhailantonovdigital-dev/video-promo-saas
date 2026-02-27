from __future__ import annotations

import os
import uuid
import hashlib
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
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
from app.models.prompt_history import PromptHistory

router = APIRouter(prefix="/cabinet", tags=["cabinet"], include_in_schema=False)

FILES_TTL_DAYS = int(os.getenv("FILES_TTL_DAYS", "30"))
FACE_PROFILE_TTL_DAYS = int(os.getenv("FACE_PROFILE_TTL_DAYS", "365"))

# Включатель (чтобы потом можно было выключить без удаления кода)
CABINET_ENABLED = os.getenv("CABINET_ENABLED", "1") == "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)
    

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _storage_root() -> Path:
    root = Path(os.getenv("LOCAL_STORAGE_DIR", "./data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_rel_from_asset_key(storage_key: str) -> Path:
    # storage_key в БД хранится как относительный путь (строка)
    # Валидация нужна на случай ошибок/инъекций.
    p = Path(str(storage_key).lstrip("/"))
    if ".." in p.parts:
        raise HTTPException(status_code=400, detail="Invalid storage_key")
    return p


def _zip_add_dir(zf: zipfile.ZipFile, dir_name: str) -> None:
    # zip не хранит пустые папки автоматически — добавляем явную запись каталога
    if not dir_name.endswith("/"):
        dir_name += "/"
    info = zipfile.ZipInfo(dir_name)
    zf.writestr(info, b"")


def _file_sha256(abs_path: Path) -> str:
    h = hashlib.sha256()
    with abs_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _human_dt(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _safe_filename(name: str, default: str) -> str:
    n = (name or "").strip() or default
    return n.replace("/", "_").replace("\\", "_")


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

    arch_q = await db.execute(
        select(Asset)
        .where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind == "archive",
        )
        .order_by(Asset.created_at.desc())
        .limit(1)
    )
    latest_archive = arch_q.scalar_one_or_none()

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

    # список картинок для выбора
    gen_q = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind == "generated_image",
        ).order_by(Asset.created_at.asc())
    )
    generated = gen_q.scalars().all()

    select_images_html = ""
    if order.status == "awaiting_selection" and generated:
        items = ""
        for a in generated:
            items += f"""
            <label style="display:block;margin:6px 0">
              <input type="checkbox" name="selected_asset_ids" value="{a.id}">
              {a.filename} <span class="muted">({(a.meta or {}).get("style","")})</span>
            </label>
            """
        select_images_html = f"""
        <div class="card">
          <h3 style="margin-top:0">Шаг 4 — Выбор картинок</h3>
          <form method="post" action="/cabinet/orders/{order.id}/select-images">
            {items}
            <button class="btn" type="submit">Подтвердить выбор</button>
          </form>
          <p class="muted">Статус станет <code>awaiting_video_refs</code>.</p>
        </div>
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
    
    step3_html = ""
    if order.status == "awaiting_image_generation":
        step3_html = f"""
        <div class="card">
          <h3 style="margin-top:0">Шаг 3 — Фотосессия (генерация)</h3>
          <form method="post" action="/cabinet/orders/{order.id}/generate-images">
            <label class="muted">Картинок на стиль:</label>
            <input type="number" name="per_style" value="3" min="1" max="10" style="width:90px">
            <button class="btn" type="submit">Сгенерировать</button>
          </form>
          <p class="muted">Статус станет <code>awaiting_selection</code>.</p>
        </div>
        """

    # Посчитать сколько уже загружено video_ref
    video_ref_count = sum(1 for a in assets if a.kind == "video_ref")

    video_refs_html = ""
    if order.status in {"awaiting_video_refs", "kling_processing", "packaging", "done"}:
        if order.status == "awaiting_video_refs":
            video_refs_html = f"""
            <div class="card">
              <h3 style="margin-top:0">Шаг 5 — Видео-референсы (загрузка)</h3>
              <form method="post" action="/cabinet/orders/{order.id}/video-refs" enctype="multipart/form-data">
                <input type="file" name="files" multiple required accept="video/*">
                <button class="btn" type="submit">Загрузить видео</button>
              </form>
              <p class="muted">После загрузки поставим статус <code>kling_processing</code> (пока заглушка).</p>
            </div>
            """
        else:
            video_refs_html = f"""
            <div class="card">
              <h3 style="margin-top:0">Шаг 5 — Видео-референсы</h3>
              <p class="muted">Загружено видео: <b>{video_ref_count}</b>. Текущий статус: <code>{order.status}</code>.</p>
            </div>
            """

    archive_html = ""
    if order.status in {"kling_processing", "packaging", "done"} or video_ref_count > 0:
        if latest_archive and latest_archive.storage_driver == "local":
            archive_html = f"""
            <div class=\"card\">
              <h3 style=\"margin-top:0\">Шаг 6 — Архив</h3>
              <p class=\"muted\">Архив собран: <b>{_human_dt(latest_archive.created_at)}</b>. Файл: <code>{latest_archive.filename}</code></p>
              <p style=\"margin-top:10px\"><a class=\"btn\" href=\"/cabinet/orders/{order.id}/archive\">Скачать ZIP</a></p>
              <form method=\"post\" action=\"/cabinet/orders/{order.id}/build-archive\" style=\"margin-top:10px\">
                <button class=\"btn\" type=\"submit\" style=\"background:#111827\">Собрать заново</button>
              </form>
              <p class=\"muted\">Сейчас архив включает: video_ref + инструкцию + manifest + шаблоны текстов (позже добавим result_video + финальные тексты).</p>
            </div>
            """
        elif video_ref_count > 0:
            archive_html = f"""
            <div class=\"card\">
              <h3 style=\"margin-top:0\">Шаг 6 — Архив</h3>
              <p class=\"muted\">Можно собрать архив (ZIP) из загруженных референсов и служебных файлов.</p>
              <form method=\"post\" action=\"/cabinet/orders/{order.id}/build-archive\">
                <button class=\"btn\" type=\"submit\">Собрать архив</button>
              </form>
              <p class=\"muted\">Будет создан asset <code>archive</code> и появится кнопка скачивания.</p>
            </div>
            """

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

    {step3_html}
    {select_images_html}
    {video_refs_html}
    {archive_html}

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
            # Лицо/фото-профиль храним 12 месяцев (можно переопределить env FACE_PROFILE_TTL_DAYS)
            delete_after=now + timedelta(days=FACE_PROFILE_TTL_DAYS),
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

@router.post("/orders/{order_id}/generate-images")
async def cabinet_generate_images(
    order_id: str,
    per_style: int = Form(3),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    per_style = max(1, min(int(per_style or 3), 10))

    oq = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "awaiting_image_generation":
        raise HTTPException(status_code=409, detail=f"Wrong order status: {order.status}")

    sq = await db.execute(select(OrderStyle).where(OrderStyle.order_id == order.id))
    style_codes = [s.style_code for s in sq.scalars().all()]
    if not style_codes:
        raise HTTPException(status_code=400, detail="No styles selected")

    now = _now()

    # создаём заглушки картинок: generated_image
    for style_code in style_codes:
        for i in range(per_style):
            base_prompt = f"HypePack photopack. style={style_code}. shot={i+1}."
            prompt_text = base_prompt + f" variation={uuid.uuid4().hex[:10]}"
            prompt_hash = _sha256(prompt_text)

            # гарантируем уникальность для user (повторные заказы не повторяют промпты)
            tries = 0
            while True:
                ex = await db.execute(
                    select(PromptHistory.id).where(
                        PromptHistory.user_id == user.id,
                        PromptHistory.prompt_hash == prompt_hash,
                    )
                )
                if not ex.scalar_one_or_none():
                    break
                tries += 1
                prompt_text = base_prompt + f" variation={uuid.uuid4().hex}"
                prompt_hash = _sha256(prompt_text)
                if tries > 5:
                    break

            db.add(PromptHistory(user_id=user.id, prompt_hash=prompt_hash, prompt_text=prompt_text))

            fake_key = f"placeholder://img/u/{user.id}/o/{order.id}/{style_code}/{uuid.uuid4().hex}"
            db.add(
                Asset(
                    user_id=user.id,
                    order_id=order.id,
                    kind="generated_image",
                    storage_driver="placeholder",
                    storage_key=fake_key,
                    filename=f"{style_code}_{i+1}.png",
                    content_type="image/png",
                    size_bytes=None,
                    sha256=None,
                    delete_after=now + timedelta(days=FILES_TTL_DAYS),
                    meta={"style": style_code, "prompt_hash": prompt_hash},
                )
            )

    order.status = "awaiting_selection"
    order.updated_at = now
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.post("/orders/{order_id}/video-refs")
async def cabinet_upload_video_refs(
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

    if order.status != "awaiting_video_refs":
        raise HTTPException(status_code=409, detail=f"Wrong order status: {order.status}")

    root = _storage_root()
    now = _now()

    created_any = False
    for f in files:
        data = await f.read()
        if not data:
            continue
        created_any = True

        sha = hashlib.sha256(data).hexdigest()
        safe_name = (f.filename or "video.mp4").replace("/", "_").replace("\\", "_")

        rel = Path("uploads") / "u" / str(user.id) / "o" / str(order.id) / "video_refs" / f"{uuid.uuid4().hex}_{safe_name}"
        abs_path = root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

        db.add(
            Asset(
                user_id=user.id,
                order_id=order.id,
                kind="video_ref",
                storage_driver="local",
                storage_key=str(rel),
                filename=safe_name,
                content_type=f.content_type or "application/octet-stream",
                size_bytes=len(data),
                sha256=sha,
                delete_after=now + timedelta(days=FILES_TTL_DAYS),
            )
        )

    if not created_any:
        raise HTTPException(status_code=400, detail="All uploaded files were empty")

    # пока Kling не подключен — просто переведём статус дальше
    order.status = "kling_processing"
    order.updated_at = now
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.post("/orders/{order_id}/select-images")
async def cabinet_select_images(
    order_id: str,
    selected_asset_ids: list[str] = Form([]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    oq = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "awaiting_selection":
        raise HTTPException(status_code=409, detail=f"Wrong order status: {order.status}")

    if not selected_asset_ids:
        raise HTTPException(status_code=400, detail="Choose at least one generated image")

    # валидируем, что эти assets принадлежат заказу и kind=generated_image
    aq = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind == "generated_image",
            Asset.id.in_(selected_asset_ids),
        )
    )
    items = aq.scalars().all()
    if len(items) != len(selected_asset_ids):
        raise HTTPException(status_code=400, detail="Some selected assets are invalid")

    now = _now()
    for src in items:
        db.add(
            Asset(
                user_id=user.id,
                order_id=order.id,
                kind="selected_image",
                storage_driver=src.storage_driver,
                storage_key=src.storage_key,
                filename=src.filename,
                content_type=src.content_type,
                size_bytes=src.size_bytes,
                sha256=src.sha256,
                delete_after=now + timedelta(days=FILES_TTL_DAYS),
                meta=src.meta,
            )
        )

    order.status = "awaiting_video_refs"
    order.updated_at = now
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.post("/orders/{order_id}/build-archive")
async def cabinet_build_archive(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Шаг 6: собрать ZIP архив.
    Пока в архив кладём:
      - video_ref (загруженные референсы)
      - (опционально) profile_photo
      - manifest.json
      - instructions + шаблоны текстов/хештегов
    """
    _ensure_enabled()

    oq = await db.execute(select(Order, Plan).join(Plan, Plan.id == Order.plan_id).where(Order.id == order_id, Order.user_id == user.id))
    row = oq.first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    order, plan = row

    now = _now()
    root = _storage_root()

    # Собираем данные
    aq = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind.in_(["video_ref", "profile_photo", "selected_image", "generated_image", "result_video"]),
        ).order_by(Asset.created_at.asc())
    )
    assets = aq.scalars().all()

    video_refs = [a for a in assets if a.kind == "video_ref" and a.storage_driver == "local"]
    if not video_refs:
        raise HTTPException(status_code=400, detail="No video_ref uploaded yet")

    sq = await db.execute(select(OrderStyle).where(OrderStyle.order_id == order.id).order_by(OrderStyle.created_at.asc()))
    styles = [s.style_code for s in sq.scalars().all()]

    # Удаляем старые архивы (и файлы), чтобы не плодить мусор
    old_q = await db.execute(
        select(Asset).where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind == "archive",
        )
    )
    old_archives = old_q.scalars().all()
    for a in old_archives:
        if a.storage_driver == "local" and a.storage_key:
            try:
                abs_old = (root / _safe_rel_from_asset_key(a.storage_key)).resolve()
                if str(abs_old).startswith(str(root)) and abs_old.exists():
                    abs_old.unlink()
            except Exception:
                # если не удалось удалить файл — не падаем, просто перезапишем запись
                pass
        db.delete(a)

    rel_zip = Path("uploads") / "u" / str(user.id) / "o" / str(order.id) / "archives" / f"{uuid.uuid4().hex}_hypepack.zip"
    abs_zip = (root / rel_zip)
    abs_zip.parent.mkdir(parents=True, exist_ok=True)

    # manifest
    selected_images = [a for a in assets if a.kind == "selected_image"]
    generated_images = [a for a in assets if a.kind == "generated_image"]
    result_videos = [a for a in assets if a.kind == "result_video"]

    prompt_hashes: list[str] = []
    for a in generated_images:
        if isinstance(a.meta, dict) and a.meta.get("prompt_hash"):
            prompt_hashes.append(str(a.meta.get("prompt_hash")))
    prompt_hashes = list(dict.fromkeys([h for h in prompt_hashes if h]))

    prompts: list[dict[str, Any]] = []
    if prompt_hashes:
        pq = await db.execute(
            select(PromptHistory).where(
                PromptHistory.user_id == user.id,
                PromptHistory.prompt_hash.in_(prompt_hashes),
            )
        )
        for p in pq.scalars().all():
            prompts.append({"prompt_hash": p.prompt_hash, "prompt_text": p.prompt_text})

    manifest: dict[str, Any] = {
        "schema": "hypepack.archive.v1",
        "generated_at": now.isoformat(),
        "order": {
            "id": str(order.id),
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "plan": {"code": plan.code, "title": plan.title, "videos_count": plan.videos_count, "images_count": plan.images_count},
            "styles": styles,
        },
        "includes": {
            "video_refs": len(video_refs),
            "profile_photos": len([a for a in assets if a.kind == "profile_photo"]),
            "generated_images": len(generated_images),
            "selected_images": len(selected_images),
            "result_videos": len(result_videos),
        },
        "selected_images": [
            {
                "asset_id": str(a.id),
                "filename": a.filename,
                "storage_driver": a.storage_driver,
                "storage_key": a.storage_key,
                "meta": a.meta,
            }
            for a in selected_images
        ],
        "prompts": prompts,
        "files": [],
    }

    instruction_md = """# HypePack: что внутри архива\n\nВ этом ZIP: \n- input/video_refs/ — ваши видео-референсы\n- input/profile_photo/ — загруженные фото-профиля (если были)\n- manifest.json — техническая сводка по заказу\n- texts/ — шаблоны описаний и хештегов (пока заглушки)\n\nДальше мы добавим сюда итоговые result_video из Kling (motion-control) и финальные тексты.\n"""

    captions_md_lines = [
        "# Тексты к видео (шаблон)",
        "",
        "Заполните под свой трек: название, CTA, ссылки, призыв подписаться.",
        "",
    ]
    for i, a in enumerate(video_refs, start=1):
        captions_md_lines += [
            f"## Видео {i}",
            f"Файл: {a.filename}",
            "",
            "Описание:",
            "- ",
            "",
            "Хештеги:",
            "- ",
            "",
        ]
    captions_md = "\n".join(captions_md_lines)

    hashtags_txt = """# хештеги (шаблон)\n# добавьте жанр/настроение/референсы\n# пример: #music #newmusic #indie #твойжанр\n"""

    # Сборка ZIP
    with zipfile.ZipFile(abs_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _zip_add_dir(zf, "input")
        _zip_add_dir(zf, "input/video_refs")
        _zip_add_dir(zf, "input/profile_photo")
        _zip_add_dir(zf, "output")
        _zip_add_dir(zf, "texts")

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("INSTRUCTION.md", instruction_md)
        zf.writestr("texts/captions.md", captions_md)
        zf.writestr("texts/hashtags.txt", hashtags_txt)

        # Файлы: видео-референсы
        for idx, a in enumerate(video_refs, start=1):
            rel = _safe_rel_from_asset_key(a.storage_key)
            abs_src = (root / rel).resolve()
            arc_name = f"input/video_refs/{idx:02d}_{_safe_filename(a.filename, 'video.mp4')}"

            file_entry: dict[str, Any] = {
                "kind": a.kind,
                "asset_id": str(a.id),
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "sha256": a.sha256,
                "storage_driver": a.storage_driver,
                "storage_key": a.storage_key,
                "zip_path": arc_name,
                "missing": False,
            }

            if str(abs_src).startswith(str(root)) and abs_src.exists():
                zf.write(abs_src, arc_name)
            else:
                file_entry["missing"] = True

            manifest["files"].append(file_entry)

        # Файлы: фото-профиль (если local)
        profile_photos = [a for a in assets if a.kind == "profile_photo" and a.storage_driver == "local"]
        for idx, a in enumerate(profile_photos, start=1):
            rel = _safe_rel_from_asset_key(a.storage_key)
            abs_src = (root / rel).resolve()
            arc_name = f"input/profile_photo/{idx:02d}_{_safe_filename(a.filename, 'photo.jpg')}"
            file_entry = {
                "kind": a.kind,
                "asset_id": str(a.id),
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "sha256": a.sha256,
                "storage_driver": a.storage_driver,
                "storage_key": a.storage_key,
                "zip_path": arc_name,
                "missing": False,
            }
            if str(abs_src).startswith(str(root)) and abs_src.exists():
                zf.write(abs_src, arc_name)
            else:
                file_entry["missing"] = True
            manifest["files"].append(file_entry)

        # Перезаписываем manifest уже с files[]
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    # Создаём asset=archive
    zip_size = abs_zip.stat().st_size if abs_zip.exists() else None
    zip_sha = _file_sha256(abs_zip) if abs_zip.exists() else None
    archive_asset = Asset(
        user_id=user.id,
        order_id=order.id,
        kind="archive",
        storage_driver="local",
        storage_key=str(rel_zip),
        filename=f"HypePack_{order.id}.zip",
        content_type="application/zip",
        size_bytes=zip_size,
        sha256=zip_sha,
        delete_after=now + timedelta(days=FILES_TTL_DAYS),
        meta={"schema": manifest.get("schema"), "video_refs": len(video_refs), "styles": styles},
    )
    db.add(archive_asset)

    # статус не меняем (пока Kling заглушка). Позже сделаем: kling_processing -> awaiting_packaging -> done
    order.updated_at = now
    await db.commit()

    return RedirectResponse(f"/cabinet/orders/{order.id}", status_code=302)


@router.get("/orders/{order_id}/archive")
async def cabinet_download_archive(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_enabled()

    oq = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    order = oq.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    arch_q = await db.execute(
        select(Asset)
        .where(
            Asset.order_id == order.id,
            Asset.user_id == user.id,
            Asset.kind == "archive",
        )
        .order_by(Asset.created_at.desc())
        .limit(1)
    )
    archive = arch_q.scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not found")
    if archive.storage_driver != "local":
        raise HTTPException(status_code=409, detail="Archive storage_driver is not local")

    root = _storage_root()
    rel = _safe_rel_from_asset_key(archive.storage_key)
    abs_path = (root / rel).resolve()
    if not str(abs_path).startswith(str(root)) or not abs_path.exists():
        raise HTTPException(status_code=404, detail="Archive file missing")

    return FileResponse(
        path=str(abs_path),
        media_type="application/zip",
        filename=archive.filename or "hypepack.zip",
        headers={"Cache-Control": "no-store"},
    )
