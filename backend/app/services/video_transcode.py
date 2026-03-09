from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.services.ffmpeg_tools import get_ffmpeg_exe, probe_duration_seconds


@dataclass
class TranscodeResult:
    output_path: Path
    duration_seconds: float
    output_size_bytes: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _calc_target_video_bitrate_kbps(duration_s: float, target_size_mb: int, audio_kbps: int = 128) -> int:
    """Compute a target *video* bitrate to fit into target_size_mb including audio."""
    target_bytes = target_size_mb * 1024 * 1024
    total_bps = (target_bytes * 8) / max(duration_s, 1e-6)
    total_kbps = int(total_bps / 1000)

    # Reserve audio + container overhead.
    video_kbps = total_kbps - audio_kbps - 128
    return max(800, min(video_kbps, 30000))


def transcode_video_for_kling(
    input_path: Path,
    output_path: Path,
    *,
    max_seconds: int,
    target_size_mb: int = 95,
    fps: int = 30,
    max_height: int = 1080,
    audio_kbps: int = 128,
) -> TranscodeResult:
    """Transcode input video into an MP4 suitable for Kling constraints.

    - Keeps audio (AAC)
    - Forces duration cap (max_seconds)
    - Attempts to keep resulting file under target_size_mb
    """
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    duration = probe_duration_seconds(input_path)
    if duration is None:
        raise RuntimeError("Cannot detect video duration")

    if duration > float(max_seconds) + 0.15:
        raise RuntimeError(f"Video too long: {duration:.2f}s (limit {max_seconds}s)")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Scale down if needed; keep aspect ratio.
    vf = f"scale=-2:min({max_height}\\,ih)"
    v_kbps = _calc_target_video_bitrate_kbps(duration, target_size_mb, audio_kbps=audio_kbps)

    exe = get_ffmpeg_exe()
    cmd = [
        exe,
        "-y",
        "-i",
        str(input_path),
        "-t",
        str(int(max_seconds)),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        vf,
        "-r",
        str(int(fps)),
        "-c:v",
        "libx264",
        "-preset",
        os.getenv("FFMPEG_X264_PRESET", "veryfast"),
        "-b:v",
        f"{v_kbps}k",
        "-maxrate",
        f"{v_kbps}k",
        "-bufsize",
        f"{v_kbps * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_kbps}k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({p.returncode}): {p.stderr[-2000:]}")

    size = output_path.stat().st_size
    return TranscodeResult(
        output_path=output_path,
        duration_seconds=float(duration),
        output_size_bytes=int(size),
        video_bitrate_kbps=int(v_kbps),
        audio_bitrate_kbps=int(audio_kbps),
    )
