from __future__ import annotations

import os
from pathlib import Path


def storage_root() -> Path:
    p = os.getenv("LOCAL_STORAGE_DIR", "./data")
    return Path(p).resolve()


def safe_join_storage(key: str) -> Path:
    """Абсолютный путь внутри storage_root (без выхода наверх)."""
    root = storage_root()
    rel = Path(key)
    abs_path = (root / rel).resolve()
    if root not in abs_path.parents and abs_path != root:
        raise ValueError("Invalid storage key path")
    return abs_path
