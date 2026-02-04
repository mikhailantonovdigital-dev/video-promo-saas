from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pay-pages"])


@router.get("/pay/return", response_class=HTMLResponse)
async def pay_return() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Оплата принята</title>
  <style>
    body { font-family: system-ui, -apple-system, Arial, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; }
    .card { border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; }
    .btn { display:inline-block; padding: 12px 16px; border-radius: 12px; background:#111827; color:#fff; text-decoration:none; }
    .muted { color:#6b7280; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Оплата принята</h1>
    <p class="muted">Мы подтверждаем платёж. Обычно это занимает от нескольких секунд до пары минут.</p>
    <p>Если вы уже залогинены, откройте список заказов в Swagger или в будущем в личном кабинете.</p>
    <a class="btn" href="/docs">Открыть панель</a>
  </div>
</body>
</html>
"""


@router.get("/pay/fail", response_class=HTMLResponse)
async def pay_fail() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Оплата не прошла</title>
  <style>
    body { font-family: system-ui, -apple-system, Arial, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; }
    .card { border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; }
    .btn { display:inline-block; padding: 12px 16px; border-radius: 12px; background:#111827; color:#fff; text-decoration:none; }
    .muted { color:#6b7280; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Оплата не прошла</h1>
    <p class="muted">Попробуйте ещё раз. Если ошибка повторяется — напишите в поддержку.</p>
    <a class="btn" href="/docs">Вернуться</a>
  </div>
</body>
</html>
"""
