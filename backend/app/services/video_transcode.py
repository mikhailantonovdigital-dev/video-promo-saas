from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _calc_target_video_bitrate_kbps(duration_s: float, target_size_mb: int) -> int:
    # Target total bits per second to fit the desired size.
    # We strip audio (-an), so budget is for video only.
    target_bytes = target_size_mb * 1024 * 1024
    bps = (target_bytes * 8) / max(duration_s, 1e-6)
    kbps = int(bps / 1000)
    # sane bounds
    return max(800, min(kbps, 30000))


def transcode_for_kling(
    input_path: Path,
    output_path: Path,
    *,
    duration_s: float,
    max_seconds: int = 30,
    max_height: int = 1080,
    target_size_mb: int = 95,
    fps: int = 30,
) -> Tuple[Path, int]:
    """Transcode video to an mp4 suitable for Kling constraints.

    - trims to max_seconds
    - converts to H.264 mp4
    - strips audio
    - caps height to max_height (keeps aspect ratio)
    - targets roughly target_size_mb
    Returns (output_path, used_video_bitrate_kbps)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Scale expression: if height > max_height -> scale down, else keep original.
    vf = f"scale='if(gt(ih,{max_height}),-2,iw)':'if(gt(ih,{max_height}),{max_height},ih)'"

    bitrate_kbps = _calc_target_video_bitrate_kbps(duration_s, target_size_mb)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-t",
        str(int(max_seconds)),
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
        "-movflags",
        "+faststart",
        "-an",
        str(output_path),
    ]
    _run(cmd)
    return output_path, bitrate_kbps
