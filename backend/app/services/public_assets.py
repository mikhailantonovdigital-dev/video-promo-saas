from __future__ import annotations

import hmac
import hashlib
import os
import time
from uuid import UUID

from app.core.config import settings


def _public_base_url() -> str:
    # Можно переопределить, если домен/прокси сложные
    base = os.getenv("PUBLIC_BASE_URL")
    if base:
        return base.rstrip("/")

    domain = (settings.app_domain or "").strip()
    if not domain:
        return ""

    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")

    return f"https://{domain}".rstrip("/")


def sign_asset_url(asset_id: UUID, *, expires_in_seconds: int = 3600) -> str:
    base = _public_base_url()
    if not base:
        raise RuntimeError("PUBLIC_BASE_URL/DOMAIN is not configured")

    exp = int(time.time()) + int(expires_in_seconds)
    secret = (os.getenv("ASSET_SIGNING_SECRET") or settings.jwt_secret).encode("utf-8")
    msg = f"{asset_id}:{exp}".encode("utf-8")
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

    return f"{base}/public/assets/{asset_id}?exp={exp}&sig={sig}"


def verify_asset_sig(asset_id: str, exp: int, sig: str) -> bool:
    try:
        exp_i = int(exp)
    except Exception:
        return False

    if exp_i < int(time.time()):
        return False

    secret = (os.getenv("ASSET_SIGNING_SECRET") or settings.jwt_secret).encode("utf-8")
    msg = f"{asset_id}:{exp_i}".encode("utf-8")
    expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
