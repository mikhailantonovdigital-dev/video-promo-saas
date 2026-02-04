from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.models.style import Style
from app.schemas.style import StyleCreateIn, StyleOut, StyleUpdateIn

router = APIRouter(prefix="/admin/styles", tags=["admin"])


@router.get("", response_model=list[StyleOut], dependencies=[Depends(require_admin)])
async def admin_list_styles(db: AsyncSession = Depends(get_db)) -> list[StyleOut]:
    q = await db.execute(select(Style).order_by(Style.name.asc()))
    items = q.scalars().all()
    return [
        StyleOut(
            id=str(s.id),
            code=s.code,
            name=s.name,
            description=s.description,
            is_active=s.is_active,
        )
        for s in items
    ]


@router.post("", response_model=StyleOut, dependencies=[Depends(require_admin)])
async def admin_create_style(payload: StyleCreateIn, db: AsyncSession = Depends(get_db)) -> StyleOut:
    q = await db.execute(select(Style).where(Style.code == payload.code))
    if q.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Style code already exists")

    s = Style(code=payload.code, name=payload.name, description=payload.description)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return StyleOut(
        id=str(s.id),
        code=s.code,
        name=s.name,
        description=s.description,
        is_active=s.is_active,
    )


@router.patch("/{style_id}", response_model=StyleOut, dependencies=[Depends(require_admin)])
async def admin_update_style(style_id: str, payload: StyleUpdateIn, db: AsyncSession = Depends(get_db)) -> StyleOut:
    q = await db.execute(select(Style).where(Style.id == style_id))
    s = q.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Not found")

    if payload.name is not None:
        s.name = payload.name
    if payload.description is not None:
        s.description = payload.description
    if payload.is_active is not None:
        s.is_active = payload.is_active

    await db.commit()
    return StyleOut(
        id=str(s.id),
        code=s.code,
        name=s.name,
        description=s.description,
        is_active=s.is_active,
    )
