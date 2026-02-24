# backend/app/services/yookassa_client.py

from dataclasses import dataclass
from decimal import Decimal
import httpx


@dataclass(frozen=True)
class YooKassaClient:
    api_base: str
    shop_id: str
    secret_key: str

    async def create_payment(
        self,
        *,
        amount_rub: int,
        return_url: str,
        description: str,
        idempotence_key: str,
        metadata: dict,
        customer_email: str,          # <-- ДОБАВИЛИ
        vat_code: int = 1,            # <-- по умолчанию "без НДС"
    ) -> dict:
        value = f"{Decimal(amount_rub):.2f}"

        payload = {
            "amount": {"value": value, "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description,
            "metadata": metadata,

            # <-- ВОТ ЭТОГО НЕ ХВАТАЛО
            "receipt": {
                "customer": {"email": customer_email},
                "items": [
                    {
                        "description": "HypePack — цифровая услуга (пакет видео)",
                        "quantity": 1.000,
                        "amount": {"value": value, "currency": "RUB"},
                        "vat_code": vat_code,
                        "payment_mode": "full_payment",
                        "payment_subject": "service",
                    }
                ],
            },
        }

        headers = {"Idempotence-Key": idempotence_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.api_base}/payments",
                json=payload,
                headers=headers,
                auth=(self.shop_id, self.secret_key),
            )
            r.raise_for_status()
            return r.json()
