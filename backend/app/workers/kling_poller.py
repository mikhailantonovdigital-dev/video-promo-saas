from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.asset import Asset
from app.models.order import Order
from app.models.video_job import VideoJob
from app.services.kling_client import KlingClient, extract_task_id, extract_task_status, extract_video_url
from app.services.public_assets import sign_asset_url
from app.services.video_ref_prepare import ensure_prepared_video_ref
from app.services.storage import storage_root, safe_join_storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


POLL_INTERVAL_SECONDS = _env_int("KLING_POLL_INTERVAL_SECONDS", 30)
BATCH_SIZE = _env_int("KLING_POLL_BATCH_SIZE", 2)
MAX_ATTEMPTS = _env_int("KLING_MAX_ATTEMPTS", 5)


async def _download_to_path(url: str, dst: Path, *, timeout: float = 180.0) -> int:
    """Stream-download URL into dst. Returns bytes written."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with dst.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    if not chunk:
                        continue
                    f.write(chunk)
                    size += len(chunk)
    return size


async def _store_result_video_from_url(
    db: AsyncSession, *, job: VideoJob, video_url: str, content_type: str = "video/mp4"
) -> Asset:
    now = _now()
    ttl_days = _env_int("FILES_TTL_DAYS", 30)

    filename = f"video_{job.idx + 1:02d}.mp4"

    rel = Path("uploads") / "u" / str(job.user_id) / "o" / str(job.order_id) / "result_videos" / f"{job.id.hex}.mp4"
    abs_path = storage_root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    size = await _download_to_path(video_url, abs_path, timeout=_env_float("KLING_DOWNLOAD_TIMEOUT", 240.0))
    sha = hashlib.sha256(abs_path.read_bytes()).hexdigest()

    asset = Asset(
        user_id=job.user_id,
        order_id=job.order_id,
        kind="result_video",
        storage_driver="local",
        storage_key=str(rel),
        filename=filename,
        content_type=content_type,
        size_bytes=int(size),
        sha256=sha,
        delete_after=now + timedelta(days=ttl_days),
        meta={"job_id": str(job.id), "idx": job.idx},
        created_at=now,
    )
    db.add(asset)
    await db.flush()
    return asset


def _kling_motion_create_path() -> str:
    return os.getenv("KLING_MOTION_CREATE_PATH", "/v1/videos/motion-control")


def _kling_motion_status_path(task_id: str) -> str:
    tpl = os.getenv("KLING_MOTION_STATUS_PATH_TEMPLATE", "/v1/videos/motion-control/{id}")
    return tpl.replace("{id}", task_id)


def _kling_mode() -> str:
    return os.getenv("KLING_MODE", "std")


def _kling_character_orientation() -> str:
    # По оф. доке: video -> ref<=30s, image -> ref<=10s.
    return os.getenv("KLING_CHARACTER_ORIENTATION", "video")


def _kling_keep_original_sound() -> str:
    # по примеру некоторых API-описаний ожидается "yes"/"no"
    return os.getenv("KLING_KEEP_ORIGINAL_SOUND", "yes")


async def _submit_job(db: AsyncSession, job: VideoJob) -> None:
    now = _now()

    if job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
        job.error_message = f"Max attempts exceeded ({MAX_ATTEMPTS})"
        job.finished_at = now
        job.updated_at = now
        return

    if not job.image_asset_id or not job.video_ref_asset_id:
        job.status = "failed"
        job.error_message = "Job missing image_asset_id or video_ref_asset_id"
        job.finished_at = now
        job.updated_at = now
        return

    # Подтягиваем assets и готовим input под требования Kling.
    img_asset = await db.get(Asset, job.image_asset_id)
    if not img_asset or img_asset.storage_driver != "local":
        # generated/selected image у нас может быть placeholder — используем profile_photo.
        pq = await db.execute(
            select(Asset)
            .where(Asset.order_id == job.order_id)
            .where(Asset.user_id == job.user_id)
            .where(Asset.kind == "profile_photo")
            .where(Asset.storage_driver == "local")
            .order_by(Asset.created_at.desc())
            .limit(1)
        )
        img_asset = pq.scalar_one_or_none()

    if not img_asset:
        raise RuntimeError("No local image found for Kling (need profile_photo)")

    vid_asset = await db.get(Asset, job.video_ref_asset_id)
    if not vid_asset or vid_asset.storage_driver != "local":
        raise RuntimeError("video_ref asset missing or not local")

    prepared_vid = await ensure_prepared_video_ref(db, src=vid_asset)

    expires = _env_int("PUBLIC_ASSET_URL_TTL_SECONDS", 6 * 3600)
    image_url = sign_asset_url(img_asset.id, expires_in_seconds=expires)
    video_url = sign_asset_url(prepared_vid.id, expires_in_seconds=expires)

    # Промпт подтянем из prompt_history через manifest позже; здесь достаточно хранить hash,
    # но для API нужен prompt. Достаём prompt_text по хэшу из prompt_history в момент отправки.
    prompt = None
    if job.prompt_hash:
        from app.models.prompt_history import PromptHistory

        pq = await db.execute(
            select(PromptHistory.prompt_text).where(
                PromptHistory.user_id == job.user_id,
                PromptHistory.prompt_hash == job.prompt_hash,
            )
        )
        r = pq.first()
        if r:
            prompt = r[0]

    if not prompt:
        prompt = "Vertical short promo video. No text overlay, no watermark."

    body = {
        "prompt": prompt,
        "image_url": image_url,
        "video_url": video_url,
        "keep_original_sound": _kling_keep_original_sound(),
        "character_orientation": _kling_character_orientation(),
        "mode": _kling_mode(),
        "callback_url": os.getenv("KLING_CALLBACK_URL") or "",
        "external_task_id": str(job.id),
    }

    client = KlingClient(timeout=_env_float("KLING_HTTP_TIMEOUT", 60.0))
    resp = await client.post(_kling_motion_create_path(), json=body)

    task_id = extract_task_id(resp)
    if not task_id:
        raise RuntimeError(f"Kling did not return task_id. Response: {resp}")

    job.provider_task_id = task_id
    job.status = "processing"
    job.attempts = int(job.attempts or 0) + 1
    job.request_payload = body
    job.response_payload = resp
    job.started_at = job.started_at or now
    job.next_poll_at = now + timedelta(seconds=POLL_INTERVAL_SECONDS)
    job.updated_at = now


async def _poll_job(db: AsyncSession, job: VideoJob) -> None:
    now = _now()

    if not job.provider_task_id:
        # если почему-то lost state
        job.status = "queued"
        job.next_poll_at = now
        job.updated_at = now
        return

    client = KlingClient(timeout=_env_float("KLING_HTTP_TIMEOUT", 60.0))
    resp = await client.get(_kling_motion_status_path(job.provider_task_id))

    status_raw = (extract_task_status(resp) or "").lower()
    job.response_payload = resp

    # Нормализуем
    if status_raw in {"succeed", "success", "completed", "done"}:
        video_url = extract_video_url(resp)
        if not video_url:
            raise RuntimeError(f"Kling task succeeded but no video url found. Response: {resp}")

        asset = await _store_result_video_from_url(db, job=job, video_url=video_url)

        job.result_asset_id = asset.id
        job.status = "succeeded"
        job.finished_at = now
        job.next_poll_at = None
        job.updated_at = now
        return

    if status_raw in {"failed", "error"}:
        job.status = "failed"
        job.error_message = str(resp.get("message") or resp)
        job.finished_at = now
        job.next_poll_at = None
        job.updated_at = now
        return

    # иначе продолжаем ждать
    job.status = "processing"
    job.next_poll_at = now + timedelta(seconds=POLL_INTERVAL_SECONDS)
    job.updated_at = now


async def _maybe_update_order_status(db: AsyncSession, order_id) -> None:
    now = _now()

    oq = await db.execute(select(Order).where(Order.id == order_id))
    order = oq.scalar_one_or_none()
    if not order:
        return

    jq = await db.execute(select(VideoJob.status).where(VideoJob.order_id == order_id))
    statuses = [r[0] for r in jq.all()]
    if not statuses:
        return

    terminal = {"succeeded", "failed"}
    if not all(s in terminal for s in statuses):
        return

    if any(s == "failed" for s in statuses):
        order.status = "kling_failed"
        order.updated_at = now
        return

    # all succeeded
    if order.status == "done":
        return

    order.status = "packaging"
    order.updated_at = now

    # Автосборка финального архива + перевод заказа в done.
    try:
        from app.services.archive_builder import build_order_archive

        # Для manifest считаем, что заказ уже готов.
        order.status = "done"
        order.updated_at = _now()
        await build_order_archive(db, order=order, user_id=order.user_id, force_rebuild=True)
    except Exception as e:
        # Оставляем packaging, чтобы можно было вручную пересобрать/починить.
        # Ошибку пишем в последний job ниже по стеку.
        order.status = "packaging"
        order.updated_at = _now()


async def process_kling_jobs_once(order_id: Optional[str] = None) -> int:
    """Один проход поллера. Возвращает количество обработанных джоб.

    Если передан order_id — обрабатываем job'ы только этого заказа (удобно для кнопки в кабинете).
    """
    processed = 0
    now = _now()

    async with AsyncSessionLocal() as db:
        stmt = (
            select(VideoJob)
            .where(VideoJob.provider == "kling")
            .where(VideoJob.status.in_(["queued", "processing"]))
            .where(or_(VideoJob.next_poll_at.is_(None), VideoJob.next_poll_at <= now))
        )

        if order_id:
            try:
                oid = uuid.UUID(str(order_id))
            except Exception:
                oid = None
            if oid:
                stmt = stmt.where(VideoJob.order_id == oid)

        stmt = (
            stmt.order_by(VideoJob.created_at.asc())
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )

        q = await db.execute(stmt)
        jobs = q.scalars().all()

        for job in jobs:
            try:
                if job.status == "queued":
                    await _submit_job(db, job)
                else:
                    await _poll_job(db, job)

                await _maybe_update_order_status(db, job.order_id)
                processed += 1
            except Exception as e:
                # не валим поллер целиком: сохраняем ошибку и попробуем ещё раз
                now2 = _now()
                job.error_message = str(e)
                job.attempts = int(job.attempts or 0) + 1
                job.updated_at = now2

                if job.attempts >= MAX_ATTEMPTS:
                    job.status = "failed"
                    job.finished_at = now2
                    job.next_poll_at = None
                else:
                    job.status = "queued"
                    job.next_poll_at = now2 + timedelta(seconds=POLL_INTERVAL_SECONDS)

        await db.commit()

    return processed


async def kling_poller_loop(stop_event: asyncio.Event) -> None:
    """Бесконечный поллер (для MVP)."""
    # если Kling не сконфигурирован - просто не запускаем
    if not (os.getenv("KLING_API_TOKEN") or (os.getenv("KLING_ACCESS_KEY") and os.getenv("KLING_SECRET_KEY"))):
        return

    while not stop_event.is_set():
        try:
            await process_kling_jobs_once()
        except Exception:
            # игнорируем системные ошибки, попробуем позже
            pass

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(POLL_INTERVAL_SECONDS))
        except asyncio.TimeoutError:
            continue


def start_kling_poller(app) -> None:
    if os.getenv("KLING_POLL_ENABLED", "1") != "1":
        return

    if getattr(app.state, "kling_stop_event", None):
        return

    stop_event = asyncio.Event()
    app.state.kling_stop_event = stop_event
    app.state.kling_task = asyncio.create_task(kling_poller_loop(stop_event))


async def stop_kling_poller(app) -> None:
    stop_event: Optional[asyncio.Event] = getattr(app.state, "kling_stop_event", None)
    task = getattr(app.state, "kling_task", None)

    if stop_event:
        stop_event.set()

    if task:
        try:
            await task
        except Exception:
            pass
