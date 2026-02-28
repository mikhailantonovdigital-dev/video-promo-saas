from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def probe_duration_seconds(path: Path) -> Optional[float]:
    """Return duration in seconds if can be determined, else None.

    Prefers ffprobe (part of ffmpeg). This is robust for MOV/MP4 from phones.
    """
    try:
        # ffprobe prints duration as float seconds
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        if not out:
            return None
        return float(out)
    except Exception:
        return None
