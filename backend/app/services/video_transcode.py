from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple


def _ffmpeg_exe() -> str:
    """Return path to ffmpeg binary.

    Prefer bundled binary from imageio-ffmpeg to avoid OS-level installs on Render.
    """
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "")[-2000:]
        raise RuntimeError(f"ffmpeg failed (code={p.returncode}). Tail:\n{tail}")


def _calc_target_video_bitrate_kbps(duration_s: float, target_size_mb: int, audio_kbps: int = 128) -> int:
    """Compute target VIDEO bitrate to fit total file size budget.

    We reserve audio_kbps for audio track and keep some overhead for MP4 container.
    """
    target_bytes = target_size_mb * 1024 * 1024
    total_bps = (target_bytes * 8) / max(duration_s, 1e-6)
    total_kbps = int(total_bps / 1000)

    video_kbps = total_kbps - int(audio_kbps) - 128
    return max(800, min(video_kbps, 30000))


def transcode_for_kling(
    input_path: Path,
    output_path: Path,
    *,
    duration_s: float,
    max_seconds: int = 30,
    max_height: int = 1080,
    target_size_mb: int = 95,
    fps: int = 30,
    audio_kbps: int = 128,
) -> Tuple[Path, int]:
    """Transcode video to an mp4 suitable for Kling constraints.

    - trims to max_seconds
    - converts to H.264 mp4
    - keeps audio (AAC) for later socials usage
    - caps height to max_height (keeps aspect ratio)
    - targets roughly target_size_mb

    Returns (output_path, used_video_bitrate_kbps)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exe = _ffmpeg_exe()

    # Scale expression: if height > max_height -> scale down, else keep original.
    vf = f"scale='if(gt(ih,{max_height}),-2,iw)':'if(gt(ih,{max_height}),{max_height},ih)'"

    bitrate_kbps = _calc_target_video_bitrate_kbps(duration_s, target_size_mb, audio_kbps=audio_kbps)

    cmd = [
        exe,
        "-y",
        "-hide_banner",
        "-i",
        str(input_path),
        "-t",
        str(int(max_seconds)),

        # Map video and audio (audio optional)
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
        "veryfast",
        "-b:v",
        f"{bitrate_kbps}k",
        "-maxrate",
        f"{bitrate_kbps}k",
        "-bufsize",
        f"{bitrate_kbps * 2}k",
        "-pix_fmt",
        "yuv420p",

        # Keep audio
        "-c:a",
        "aac",
        "-b:a",
        f"{int(audio_kbps)}k",
        "-ac",
        "2",

        "-movflags",
        "+faststart",
        str(output_path),
    ]

    _run(cmd)
    return output_path, bitrate_kbps
