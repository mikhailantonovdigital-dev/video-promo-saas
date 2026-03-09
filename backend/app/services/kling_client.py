from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from jose import jwt


@dataclass
class KlingAPIError(RuntimeError):
    status_code: int
    code: Optional[int]
    message: str
    request_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None

    def __str__(self) -> str:
        rid = f" request_id={self.request_id}" if self.request_id else ""
        api_code = f" code={self.code}" if self.code is not None else ""
        return f"Kling API error: http={self.status_code}{api_code}{rid} msg={self.message}"


def _base_url() -> str:
    return os.getenv("KLING_API_BASE_URL", "https://api-singapore.klingai.com").rstrip("/")


def _ensure_bearer(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    if t.lower().startswith("bearer "):
        return t
    return f"Bearer {t}"


def _make_jwt_token() -> str:
    access_key = os.getenv("KLING_ACCESS_KEY")
    secret_key = os.getenv("KLING_SECRET_KEY")
    if not access_key or not secret_key:
        raise RuntimeError("Kling credentials missing: set KLING_API_TOKEN or KLING_ACCESS_KEY+KLING_SECRET_KEY")

    now = int(time.time())
    payload = {"iss": access_key, "exp": now + 1800, "nbf": now - 5}
    return jwt.encode(payload, secret_key, algorithm="HS256")


def _auth_header_value() -> str:
    token = os.getenv("KLING_API_TOKEN")
    if token:
        return _ensure_bearer(token)
    return _ensure_bearer(_make_jwt_token())


class KlingClient:
    def __init__(self, *, timeout: float = 60.0):
        self._timeout = timeout

    async def get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def post(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def _request(self, method: str, path: str, *, json: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{_base_url()}{path if path.startswith('/') else '/' + path}"
        headers = {"Authorization": _auth_header_value()}
        if method.upper() in {"POST", "PUT", "PATCH"}:
            headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.request(method, url, headers=headers, json=json)

        status_code = resp.status_code
        try:
            payload = resp.json()
        except Exception:
            raise KlingAPIError(status_code=status_code, code=None, message=(resp.text or "")[:500])

        if status_code >= 400:
            raise KlingAPIError(
                status_code=status_code,
                code=payload.get("code"),
                message=str(payload.get("message") or payload)[:500],
                request_id=payload.get("request_id"),
                payload=payload,
            )

        # Kling style: {"code":0,...}
        if isinstance(payload, dict) and payload.get("code") not in (0, None):
            raise KlingAPIError(
                status_code=status_code,
                code=payload.get("code"),
                message=str(payload.get("message") or payload)[:500],
                request_id=payload.get("request_id"),
                payload=payload,
            )

        return payload


def extract_task_id(resp: dict[str, Any]) -> Optional[str]:
    data = (resp or {}).get("data") or {}
    return data.get("task_id") or data.get("taskId")


def extract_task_status(resp: dict[str, Any]) -> Optional[str]:
    data = (resp or {}).get("data") or {}
    return data.get("task_status") or data.get("taskStatus")


def extract_video_url(resp: dict[str, Any]) -> Optional[str]:
    data = (resp or {}).get("data") or {}
    tr = data.get("task_result") or data.get("taskResult") or {}
    videos = tr.get("videos") or []
    if isinstance(videos, list) and videos:
        v0 = videos[0] or {}
        return v0.get("url") or v0.get("watermark_url")
    return None
