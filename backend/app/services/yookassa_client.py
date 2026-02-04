from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx


@dataclass(frozen=True)
class YooKassaClient:
    api_base: str
    shop_id: str
    secret_key: str

    async def create_payment(self, *, amount_rub: int, return_url: str, description: str, idempotence_key: str, metadata: dict) -> dict:
        # ЮKassa ожидает value строкой с 2 знаками
        value = f"{Decimal(amount_rub):.2f}"

        payload = {
            "amount": {"value": value, "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description,
            "metadata": metadata,
        }

        headers = {"Idempotence-Key": idempotence_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.api_base}/payments",
                json=payload,
                headers=headers,
                auth=(self.shop_id, self.secret_key),  # Basic Auth
            )
            r.raise_for_status()
            return r.json()

    async def get_payment(self, *, payment_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.api_base}/payments/{payment_id}",
                auth=(self.shop_id, self.secret_key),
            )
            r.raise_for_status()
            return r.json()
