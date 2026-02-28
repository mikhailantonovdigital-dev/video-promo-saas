from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.services.storage import safe_join_storage, storage_root
from app.services.video_transcode import transcode_video_for_kling
from app.services.ffmpeg_tools import probe_duration_seconds


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def kling_max_seconds() -> int:
    """Derive max seconds from Kling settings (per official docs)."""
    orientation = os.getenv("KLING_CHARACTER_ORIENTATION", "video").lower().strip()
    if orientation == "image":
        return 10
    return 30


async def ensure_prepared_video_ref(db: AsyncSession, *, src: Asset) -> Asset:
    """Return an asset that is safe to pass to Kling as video_url.

    If src is already within Kling limits (<=100MB, duration ok), we may return src.
    Otherwise we create a new local MP4 asset kind=video_ref_prepared.
    """
    if src.storage_driver != "local" or not src.storage_key:
        raise RuntimeError("video_ref must be local")

    # If prepared already exists - reuse.
    q = await db.execute(
        select(Asset)
        .where(Asset.user_id == src.user_id)
        .where(Asset.order_id == src.order_id)
        .where(Asset.kind == "video_ref_prepared")
        .where(Asset.storage_driver == "local")
        .order_by(Asset.created_at.desc())
        .limit(20)
    )
    for existing in q.scalars().all():
        if isinstance(existing.meta, dict) and existing.meta.get("original_asset_id") == str(src.id):
            try:
                p = safe_join_storage(existing.storage_key)
                if p.exists():
                    return existing
            except Exception:
                continue

    abs_src = safe_join_storage(src.storage_key)
    if not abs_src.exists():
        raise RuntimeError("Source video file not found")

    max_seconds = kling_max_seconds()
    duration = probe_duration_seconds(abs_src)
    if duration is None:
        raise RuntimeError("Cannot detect video duration")
    if duration > float(max_seconds) + 0.15:
        raise RuntimeError(f"Video duration {duration:.2f}s exceeds Kling limit {max_seconds}s")

    # Kling hard limit from docs
    max_size_mb = _env_int("KLING_MAX_VIDEO_MB", 100)
    max_size_bytes = max_size_mb * 1024 * 1024

    # If already small enough - use as is.
    try:
        if (src.size_bytes or abs_src.stat().st_size) <= max_size_bytes:
            return src
    except Exception:
        pass

    # Transcode to <= ~95MB (reserve some overhead)
    target_size_mb = min(_env_int("KLING_TARGET_VIDEO_MB", 95), max_size_mb - 3)

    rel_out = (
        Path("uploads")
        / "u"
        / str(src.user_id)
        / "o"
        / str(src.order_id)
        / "video_refs_prepared"
        / f"{src.id.hex}_{_now().strftime('%Y%m%d%H%M%S')}.mp4"
    )
    abs_out = storage_root() / rel_out

    res = transcode_video_for_kling(
        abs_src,
        abs_out,
        max_seconds=max_seconds,
        target_size_mb=target_size_mb,
        fps=_env_int("KLING_TRANSCODE_FPS", 30),
        max_height=_env_int("KLING_TRANSCODE_MAX_HEIGHT", 1080),
        audio_kbps=_env_int("KLING_TRANSCODE_AUDIO_KBPS", 128),
    )

    if res.output_size_bytes > max_size_bytes:
        raise RuntimeError(
            f"Prepared video still too large: {res.output_size_bytes / (1024*1024):.1f}MB (limit {max_size_mb}MB)"
        )

    # hash
    sha = hashlib.sha256(res.output_path.read_bytes()).hexdigest()

    ttl_days = _env_int("FILES_TTL_DAYS", 30)
    now = _now()
    prepared = Asset(
        user_id=src.user_id,
        order_id=src.order_id,
        kind="video_ref_prepared",
        storage_driver="local",
        storage_key=str(rel_out),
        filename=(src.filename or "video.mp4").rsplit(".", 1)[0] + ".mp4",
        content_type="video/mp4",
        size_bytes=int(res.output_size_bytes),
        sha256=sha,
        delete_after=now + timedelta(days=ttl_days),
        meta={
            "original_asset_id": str(src.id),
            "duration_seconds": float(res.duration_seconds),
            "video_bitrate_kbps": int(res.video_bitrate_kbps),
            "audio_bitrate_kbps": int(res.audio_bitrate_kbps),
            "target_size_mb": int(target_size_mb),
        },
        created_at=now,
    )
    db.add(prepared)
    await db.flush()
    return prepared
