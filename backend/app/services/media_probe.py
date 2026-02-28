from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VideoProbeResult:
    duration_seconds: float


class VideoProbeError(RuntimeError):
    pass


def _read_u32be(b: bytes) -> int:
    return int.from_bytes(b, "big", signed=False)


def _read_u64be(b: bytes) -> int:
    return int.from_bytes(b, "big", signed=False)


def _iter_atoms(f, *, end_pos: int):
    """Yield (atom_type, payload_start, payload_end) inside a container until end_pos."""
    while f.tell() < end_pos:
        hdr = f.read(8)
        if len(hdr) < 8:
            return

        size32 = _read_u32be(hdr[0:4])
        atype = hdr[4:8].decode("latin-1", errors="replace")

        header_size = 8
        if size32 == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = _read_u64be(ext)
            header_size = 16
        elif size32 == 0:
            # extends to end of file/container
            size = end_pos - (f.tell() - 8)
        else:
            size = size32

        if size < header_size:
            return

        payload_start = f.tell()
        payload_end = (f.tell() - header_size) + size
        if payload_end > end_pos:
            payload_end = end_pos

        yield atype, payload_start, payload_end

        f.seek(payload_end)


def probe_mp4_duration_seconds(path: Path) -> float:
    """Probe MP4/MOV duration via moov/mvhd atoms.

    Works for most common MP4/MOV uploads without ffmpeg.
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise VideoProbeError("File does not exist")

    if p.stat().st_size < 16:
        raise VideoProbeError("File too small")

    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        eof = f.tell()
        f.seek(0)

        moov = None
        for atype, start, end in _iter_atoms(f, end_pos=eof):
            if atype == "moov":
                moov = (start, end)
                break

        if not moov:
            raise VideoProbeError("No moov atom")

        moov_start, moov_end = moov
        f.seek(moov_start)

        mvhd = None
        for atype, start, end in _iter_atoms(f, end_pos=moov_end):
            if atype == "mvhd":
                mvhd = (start, end)
                break

        if not mvhd:
            raise VideoProbeError("No mvhd atom")

        mvhd_start, mvhd_end = mvhd
        f.seek(mvhd_start)
        buf = f.read(mvhd_end - mvhd_start)
        if len(buf) < 4:
            raise VideoProbeError("Invalid mvhd")

        version = buf[0]
        off = 4  # version+flags

        if version == 0:
            off += 8  # creation+modification
            if len(buf) < off + 8:
                raise VideoProbeError("Invalid mvhd v0")
            timescale = _read_u32be(buf[off : off + 4])
            duration = _read_u32be(buf[off + 4 : off + 8])
        elif version == 1:
            off += 16
            if len(buf) < off + 12:
                raise VideoProbeError("Invalid mvhd v1")
            timescale = _read_u32be(buf[off : off + 4])
            duration = _read_u64be(buf[off + 4 : off + 12])
        else:
            raise VideoProbeError(f"Unsupported mvhd version: {version}")

        if timescale <= 0 or duration <= 0:
            raise VideoProbeError("Invalid duration/timescale")

        return float(duration) / float(timescale)


def probe_video_duration_seconds(path: Path) -> VideoProbeResult:
    dur = probe_mp4_duration_seconds(path)
    if not (dur > 0):
        raise VideoProbeError("Duration is not positive")
    return VideoProbeResult(duration_seconds=float(dur))
