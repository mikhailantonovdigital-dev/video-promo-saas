from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401  (важно: чтобы модели импортнулись)

from app.api.routers.auth import router as auth_router
from app.api.routers.styles import router as styles_router
from app.api.routers.admin_styles import router as admin_styles_router

from app.api.routers.plans import router as plans_router
from app.api.routers.checkout import router as checkout_router
from app.api.routers.webhooks import router as webhooks_router

from app.api.routers.pay_pages import router as pay_pages_router

app = FastAPI(title="Video Promo SaaS", version="0.0.1")


@app.on_event("startup")
async def startup() -> None:
    # 1) создаём таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2) сидируем планы (в отдельной сессии)
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.plan import Plan

    async with AsyncSessionLocal() as db:
        q = await db.execute(select(Plan).limit(1))
        exists = q.scalar_one_or_none()
        if not exists:
            db.add_all(
                [
                    Plan(code="test_1", title="1 тестовое видео", images_count=1, videos_count=1),
                    Plan(code="month_30", title="30 видео (1/день на месяц)", images_count=30, videos_count=30),
                    Plan(code="month_90", title="90 видео (3/день на месяц)", images_count=90, videos_count=90),
                ]
            )
            await db.commit()


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(styles_router, prefix="/api/v1")
app.include_router(admin_styles_router, prefix="/api/v1")

app.include_router(plans_router, prefix="/api/v1")
app.include_router(checkout_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")

app.include_router(pay_pages_router)

from fastapi.responses import HTMLResponse

@app.get("/pay/return", response_class=HTMLResponse, include_in_schema=False)
async def pay_return() -> str:
    return """
<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Оплата принята</title></head>
<body style="font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px">
  <h1>Оплата принята</h1>
  <p style="color:#6b7280">Мы подтверждаем платёж. Обычно это занимает до пары минут.</p>
  <p><a href="/docs">Открыть панель</a></p>
</body>
</html>
"""

@app.get("/pay/fail", response_class=HTMLResponse, include_in_schema=False)
async def pay_fail() -> str:
    return """
<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Оплата не прошла</title></head>
<body style="font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px">
  <h1>Оплата не прошла</h1>
  <p style="color:#6b7280">Попробуйте ещё раз или напишите в поддержку.</p>
  <p><a href="/docs">Вернуться</a></p>
</body>
</html>
"""

from fastapi.responses import HTMLResponse

def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui,-apple-system,Arial,sans-serif; max-width: 900px; margin: 40px auto; padding: 0 16px; }}
    nav a {{ margin-right: 12px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; }}
    .muted {{ color:#6b7280; }}
    footer {{ margin-top: 28px; color:#6b7280; font-size: 14px; }}
  </style>
</head>
<body>
  <nav>
    <a href="/">Главная</a>
    <a href="/pricing">Тарифы</a>
    <a href="/how">Как работает</a>
    <a href="/contacts">Контакты</a>
    <a href="/legal/offer">Оферта</a>
    <a href="/legal/privacy">Политика ПД</a>
    <a href="/legal/refund">Возвраты</a>
  </nav>
  <div class="card">{body}</div>
  <footer>© HypePack</footer>
</body>
</html>"""
