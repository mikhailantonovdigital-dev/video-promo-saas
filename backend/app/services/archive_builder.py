from __future__ import annotations

import json
import os
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.order import Order
from app.models.order_style import OrderStyle
from app.models.plan import Plan
from app.models.prompt_history import PromptHistory
from app.models.video_job import VideoJob
from app.services.storage import safe_join_storage, storage_root


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


FILES_TTL_DAYS = _env_int("FILES_TTL_DAYS", 30)


def _zip_add_dir(zf: zipfile.ZipFile, name: str) -> None:
    if not name.endswith("/"):
        name += "/"
    zf.writestr(name, "")


def _safe_filename(name: Optional[str], fallback: str) -> str:
    base = (name or "").strip() or fallback
    base = base.replace("/", "_").replace("\\", "_")
    return base[:180]


def _file_sha256(p: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _hashtags_from_styles(styles: list[str]) -> list[str]:
    base = [
        "#music",
        "#newmusic",
        "#reels",
        "#shorts",
        "#tiktok",
        "#verticalvideo",
    ]
    for s in styles:
        s = (s or "").strip().lower().replace(" ", "")
        if not s:
            continue
        if not s.startswith("#"):
            s = "#" + s
        base.append(s)
    out: list[str] = []
    seen = set()
    for h in base:
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


@dataclass
class BuiltArchive:
    archive_asset: Asset
    zip_path: Path
    manifest: dict[str, Any]


async def build_order_archive(
    db: AsyncSession,
    *,
    order: Order,
    user_id,
    force_rebuild: bool = True,
) -> BuiltArchive:
    """Create (or rebuild) ZIP archive for an order.

    Used by cabinet endpoint and by Kling poller on completion.
    """

    now = _now()
    root = storage_root()

    plan = await db.get(Plan, order.plan_id)
    if not plan:
        raise RuntimeError("Plan not found")

    aq = await db.execute(
        select(Asset)
        .where(
            Asset.order_id == order.id,
            Asset.user_id == user_id,
            Asset.kind.in_(
                [
                    "video_ref",
                    "video_ref_prepared",
                    "profile_photo",
                    "selected_image",
                    "generated_image",
                    "result_video",
                    "archive",
                ]
            ),
        )
        .order_by(Asset.created_at.asc())
    )
    assets = aq.scalars().all()

    video_refs = [a for a in assets if a.kind == "video_ref" and a.storage_driver == "local"]
    if not video_refs:
        raise RuntimeError("No video_ref uploaded yet")

    prepared_refs = [a for a in assets if a.kind == "video_ref_prepared" and a.storage_driver == "local"]
    profile_photos = [a for a in assets if a.kind == "profile_photo" and a.storage_driver == "local"]
    selected_images = [a for a in assets if a.kind == "selected_image"]
    generated_images = [a for a in assets if a.kind == "generated_image"]
    result_videos_local = [a for a in assets if a.kind == "result_video" and a.storage_driver == "local"]

    sq = await db.execute(
        select(OrderStyle).where(OrderStyle.order_id == order.id).order_by(OrderStyle.created_at.asc())
    )
    styles = [s.style_code for s in sq.scalars().all()]

    jq = await db.execute(
        select(VideoJob)
        .where(VideoJob.order_id == order.id, VideoJob.user_id == user_id)
        .order_by(VideoJob.idx.asc())
    )
    jobs = jq.scalars().all()

    prompt_hashes: list[str] = []
    for j in jobs:
        if j.prompt_hash:
            prompt_hashes.append(j.prompt_hash)
    for a in generated_images:
        if isinstance(a.meta, dict) and a.meta.get("prompt_hash"):
            prompt_hashes.append(str(a.meta.get("prompt_hash")))
    prompt_hashes = list(dict.fromkeys([h for h in prompt_hashes if h]))

    prompts: dict[str, str] = {}
    if prompt_hashes:
        pq = await db.execute(
            select(PromptHistory).where(
                PromptHistory.user_id == user_id,
                PromptHistory.prompt_hash.in_(prompt_hashes),
            )
        )
        for p in pq.scalars().all():
            prompts[p.prompt_hash] = p.prompt_text

    if force_rebuild:
        for a in [x for x in assets if x.kind == "archive"]:
            if a.storage_driver == "local" and a.storage_key:
                try:
                    abs_old = safe_join_storage(a.storage_key)
                    if abs_old.exists():
                        abs_old.unlink()
                except Exception:
                    pass
            db.delete(a)

    rel_zip = (
        Path("uploads")
        / "u"
        / str(user_id)
        / "o"
        / str(order.id)
        / "archives"
        / f"{uuid.uuid4().hex}_hypepack.zip"
    )
    abs_zip = root / rel_zip
    abs_zip.parent.mkdir(parents=True, exist_ok=True)

    def _rv_idx(a: Asset) -> int:
        try:
            return int((a.meta or {}).get("idx"))
        except Exception:
            return 10**9

    result_videos_local.sort(key=_rv_idx)

    hashtags = _hashtags_from_styles(styles)

    captions: list[dict[str, Any]] = []
    captions_md_lines: list[str] = []
    if result_videos_local:
        captions_md_lines += [
            "# Тексты к итоговым видео",
            "",
            "Ниже — заготовки описаний под каждое итоговое видео.",
            "Заполни под свой трек: название, артист, ссылка, CTA.",
            "",
        ]
        for i, a in enumerate(result_videos_local, start=1):
            fname = a.filename or f"video_{i:02d}.mp4"
            prompt_text = ""
            try:
                idx0 = int((a.meta or {}).get("idx"))
            except Exception:
                idx0 = i - 1
            if 0 <= idx0 < len(jobs):
                prompt_text = prompts.get(jobs[idx0].prompt_hash or "", "")

            desc = (
                f"Сцена {i}: клип под твой трек в стиле {', '.join(styles) if styles else 'HypePack'}.\n"
                "\n"
                "🎧 Трек: <название> — <артист>\n"
                "🔥 Полная версия: <ссылка>\n"
                "⬇️ Подпишись: <@ник>\n"
            )
            captions.append(
                {
                    "video_index": i,
                    "filename": fname,
                    "description": desc,
                    "hashtags": hashtags,
                    "prompt": prompt_text,
                }
            )
            captions_md_lines += [
                f"## Видео {i}",
                f"Файл: `{fname}`",
                "",
                "Описание:",
                desc,
                "",
                "Хештеги:",
                " ".join(hashtags),
                "",
            ]
            if prompt_text:
                captions_md_lines += [
                    "Промпт (для справки):",
                    "```",
                    prompt_text.strip()[:2500],
                    "```",
                    "",
                ]
    else:
        captions_md_lines += [
            "# Тексты к видео (шаблон)",
            "",
            "Итоговые видео ещё не готовы. Этот файл — шаблон.",
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
    hashtags_txt = "\n".join(["# хештеги"] + hashtags) + "\n"

    instruction_md = """# HypePack: как использовать пакет

В этом ZIP:

- `output/result_videos/` — итоговые видео (если готовы)
- `texts/` — тексты и хештеги под публикацию
- `manifest.json` — техническая сводка по заказу

Рекомендации для Reels/TikTok/Shorts:

1) Публикуй вертикально 9:16.
2) Первые 1–2 секунды — самый сильный кадр (hook).
3) В описании: название трека, артист, CTA (ссылка/подписка).
4) Хештеги: 5–12 штук, смешивай общие и тематические.
"""

    manifest: dict[str, Any] = {
        "schema": "hypepack.archive.v2",
        "generated_at": now.isoformat(),
        "order": {
            "id": str(order.id),
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "plan": {
                "code": plan.code,
                "title": plan.title,
                "videos_count": plan.videos_count,
                "images_count": plan.images_count,
            },
            "styles": styles,
        },
        "includes": {
            "video_refs": len(video_refs),
            "video_refs_prepared": len(prepared_refs),
            "profile_photos": len(profile_photos),
            "selected_images": len(selected_images),
            "result_videos": len(result_videos_local),
        },
        "video_jobs": [
            {
                "idx": j.idx,
                "status": j.status,
                "task_id": j.provider_task_id,
                "prompt_hash": j.prompt_hash,
                "prompt": prompts.get(j.prompt_hash or "", ""),
                "result_asset_id": str(j.result_asset_id) if j.result_asset_id else None,
            }
            for j in jobs
        ],
        "captions": captions,
        "files": [],
    }

    with zipfile.ZipFile(abs_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _zip_add_dir(zf, "input")
        _zip_add_dir(zf, "input/video_refs")
        _zip_add_dir(zf, "input/video_refs_prepared")
        _zip_add_dir(zf, "input/profile_photo")
        _zip_add_dir(zf, "output")
        _zip_add_dir(zf, "output/result_videos")
        _zip_add_dir(zf, "texts")

        zf.writestr("INSTRUCTION.md", instruction_md)
        zf.writestr("texts/captions.md", captions_md)
        zf.writestr("texts/captions.json", json.dumps(captions, ensure_ascii=False, indent=2))
        zf.writestr("texts/hashtags.txt", hashtags_txt)

        for idx, a in enumerate(video_refs, start=1):
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
            try:
                abs_src = safe_join_storage(a.storage_key)
                if abs_src.exists():
                    zf.write(abs_src, arc_name)
                else:
                    file_entry["missing"] = True
            except Exception:
                file_entry["missing"] = True
            manifest["files"].append(file_entry)

        for idx, a in enumerate(prepared_refs, start=1):
            arc_name = f"input/video_refs_prepared/{idx:02d}_{_safe_filename(a.filename, 'video.mp4')}"
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
            try:
                abs_src = safe_join_storage(a.storage_key)
                if abs_src.exists():
                    zf.write(abs_src, arc_name)
                else:
                    file_entry["missing"] = True
            except Exception:
                file_entry["missing"] = True
            manifest["files"].append(file_entry)

        for idx, a in enumerate(profile_photos, start=1):
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
            try:
                abs_src = safe_join_storage(a.storage_key)
                if abs_src.exists():
                    zf.write(abs_src, arc_name)
                else:
                    file_entry["missing"] = True
            except Exception:
                file_entry["missing"] = True
            manifest["files"].append(file_entry)

        for idx, a in enumerate(result_videos_local, start=1):
            arc_name = f"output/result_videos/{idx:02d}_{_safe_filename(a.filename, 'video.mp4')}"
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
            try:
                abs_src = safe_join_storage(a.storage_key)
                if abs_src.exists():
                    zf.write(abs_src, arc_name)
                else:
                    file_entry["missing"] = True
            except Exception:
                file_entry["missing"] = True
            manifest["files"].append(file_entry)

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    zip_size = abs_zip.stat().st_size if abs_zip.exists() else None
    zip_sha = _file_sha256(abs_zip) if abs_zip.exists() else None
    archive_asset = Asset(
        user_id=user_id,
        order_id=order.id,
        kind="archive",
        storage_driver="local",
        storage_key=str(rel_zip),
        filename=f"HypePack_{order.id}.zip",
        content_type="application/zip",
        size_bytes=zip_size,
        sha256=zip_sha,
        delete_after=now + timedelta(days=FILES_TTL_DAYS),
        meta={"schema": manifest.get("schema"), "result_videos": len(result_videos_local), "styles": styles},
        created_at=now,
    )
    db.add(archive_asset)
    await db.flush()

    return BuiltArchive(archive_asset=archive_asset, zip_path=abs_zip, manifest=manifest)
