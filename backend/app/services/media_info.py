from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _ffmpeg_exe() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def probe_duration_seconds(path: Path) -> Optional[float]:
    try:
        exe = _ffmpeg_exe()
        p = subprocess.run(
            [exe, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        m = _DURATION_RE.search(p.stderr or "")
        if not m:
            return None
        hh, mm, ss = m.groups()
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    except Exception:
        return None
