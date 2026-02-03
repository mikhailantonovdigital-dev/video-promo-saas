from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.style import Style
from app.schemas.style import StyleOut

router = APIRouter(prefix="/styles", tags=["styles"])


@router.get("", response_model=list[StyleOut])
async def list_styles(db: AsyncSession = Depends(lambda: AsyncSessionLocal())) -> list[StyleOut]:
    q = await db.execute(select(Style).where(Style.is_active.is_(True)).order_by(Style.weight.desc(), Style.name.asc()))
    items = q.scalars().all()
    return [StyleOut(id=str(s.id), code=s.code, name=s.name, description=s.description, is_active=s.is_active) for s in items]
