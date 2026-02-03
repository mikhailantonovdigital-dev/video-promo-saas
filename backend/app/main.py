from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401  (важно: чтобы модели импортнулись)

from app.api.routers.auth import router as auth_router
from app.api.routers.styles import router as styles_router
from app.api.routers.admin_styles import router as admin_styles_router

app = FastAPI(title="Video Promo SaaS", version="0.0.1")


@app.on_event("startup")
async def startup() -> None:
    # Для MVP-скелета делаем auto-create таблиц.
    # Позже заменим на Alembic миграции.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(styles_router, prefix="/api/v1")
app.include_router(admin_styles_router, prefix="/api/v1")
