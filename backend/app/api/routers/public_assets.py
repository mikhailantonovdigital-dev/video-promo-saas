from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.asset import Asset
from app.services.public_assets import verify_asset_sig
from app.services.storage import safe_join_storage

router = APIRouter(prefix="/public", tags=["public"], include_in_schema=False)


@router.get("/assets/{asset_id}")
async def get_public_asset(
    asset_id: str,
    exp: int = Query(...),
    sig: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not verify_asset_sig(asset_id=asset_id, exp=exp, sig=sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        asset_uuid = UUID(asset_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Asset not found")

    q = await db.execute(select(Asset).where(Asset.id == asset_uuid))
    asset = q.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.storage_driver != "local":
        raise HTTPException(status_code=404, detail="Asset storage is not local")

    try:
        abs_path = safe_join_storage(asset.storage_key)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid path")

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(abs_path),
        media_type=asset.content_type or "application/octet-stream",
        filename=asset.filename or "file",
    )
