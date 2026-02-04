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

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>HypePack API</title>
  <style>
    body { font-family: system-ui, -apple-system, Arial, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; }
    .card { border: 1px solid #e5e7eb; border-radius: 16px; padding: 20px; }
    .btn { display:inline-block; padding: 12px 16px; border-radius: 12px; background:#111827; color:#fff; text-decoration:none; margin-right: 8px; }
    .muted { color:#6b7280; }
  </style>
</head>
<body>
  <div class="card">
    <h1>HypePack API работает</h1>
    <p class="muted">Это технический endpoint для сервиса. Пользовательский кабинет будет добавлен позже.</p>
    <a class="btn" href="/docs">Swagger</a>
    <a class="btn" href="/health">Health</a>
  </div>
</body>
</html>
"""

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

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def site_home() -> str:
    return _page("HypePack — промо-видео для треков", """
<h1>HypePack</h1>
<p>Сервис для музыкантов: генерируем пакет вертикальных видео для продвижения трека.</p>
<ul>
  <li>Видео под вертикальные форматы</li>
  <li>Тексты: заголовки/описания/хештеги + инструкции публикации</li>
  <li>Вы публикуете сами, мы не занимаемся дистрибуцией</li>
</ul>
<p class="muted">Пользователь подтверждает права на контент и согласие на использование своего лица.</p>
""")

@app.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def site_pricing() -> str:
    return _page("Тарифы — HypePack", """
<h1>Тарифы</h1>
<ul>
  <li><b>Тест:</b> 1 видео</li>
  <li><b>Пакет:</b> 30 видео (1/день на месяц)</li>
  <li><b>Пакет:</b> 90 видео (3/день на месяц)</li>
</ul>
<p class="muted">Итоговая цена рассчитывается автоматически (не ниже 2× себестоимости).</p>
""")

@app.get("/how", response_class=HTMLResponse, include_in_schema=False)
async def site_how() -> str:
    return _page("Как работает — HypePack", """
<h1>Как оказывается услуга</h1>
<ol>
  <li>Регистрация и подтверждение email</li>
  <li>Оплата</li>
  <li>Загрузка ваших фото → обучение профиля лица</li>
  <li>Выбор стилей → фотосессия → подтверждение выбора</li>
  <li>Загрузка видео-референсов → генерация видео</li>
  <li>Скачивание архива: видео + тексты + инструкции</li>
</ol>
<p class="muted">Хранение файлов: 30 дней после выдачи результата, затем удаляем.</p>
""")

@app.get("/contacts", response_class=HTMLResponse, include_in_schema=False)
async def site_contacts() -> str:
    return _page("Контакты — HypePack", """
<h1>Контакты</h1>
<p>Email поддержки: <b>support@hypepack.ru</b> (замени на реальный)</p>
<p>Telegram: <b>@your_contact</b> (замени на реальный)</p>
<hr/>
<p><b>Реквизиты продавца</b> (обязательно заполнить реальными данными):</p>
<ul>
  <li>Название: …</li>
  <li>ИНН: …</li>
  <li>ОГРН/ОГРНИП: …</li>
  <li>Адрес: …</li>
</ul>
""")

@app.get("/legal/offer", response_class=HTMLResponse, include_in_schema=False)
async def legal_offer() -> str:
    return _page("Оферта — HypePack", """
<h1>Публичная оферта</h1>
<p>Цифровая услуга: генерация промо-материалов (видео и тексты) для трека.</p>
<p><b>Срок оказания:</b> до … (укажи реальный SLA).</p>
<p><b>Права и согласия:</b> пользователь гарантирует права на контент и согласие на использование собственного лица.</p>
""")

@app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
async def legal_privacy() -> str:
    return _page("Политика ПД — HypePack", """
<h1>Политика обработки персональных данных</h1>
<p>Обрабатываем email и загружаемые материалы (фото/видео) строго для оказания услуги.</p>
<p>Срок хранения файлов: 30 дней после выдачи результата, затем удаление.</p>
""")

@app.get("/legal/refund", response_class=HTMLResponse, include_in_schema=False)
async def legal_refund() -> str:
    return _page("Возвраты — HypePack", """
<h1>Возвраты и отмена</h1>
<p>Если генерация ещё не запускалась — возможна отмена по запросу.</p>
<p>Если генерация запущена — условия возврата описаны в оферте.</p>
""")

