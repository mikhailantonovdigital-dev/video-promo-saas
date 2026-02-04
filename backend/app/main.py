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

SELLER = {
    "name": "ИП Антонова Евгения Юрьевна",
    "email": "inrestart@yandex.ru",
    "telegram": "@mikhailantonov19",
    "inn": "121603658990",
    "ogrnip": "322120000026481",
    "address": "425003, Россия, Респ. Марий Эл, г. Волжск, ул. Полевая, д. 74",
}

SLA_TEXT = "до 2 часов"
FILES_TTL_DAYS = 30

def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui,-apple-system,Arial,sans-serif; max-width: 980px; margin: 40px auto; padding: 0 16px; line-height: 1.45; }}
    nav a {{ margin-right: 12px; text-decoration:none; }}
    nav {{ margin-bottom: 16px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 16px; padding: 22px; }}
    .muted {{ color:#6b7280; }}
    .pill {{ display:inline-block; padding: 6px 10px; border-radius: 999px; background:#f3f4f6; margin-right: 8px; }}
    .btn {{ display:inline-block; padding: 10px 14px; border-radius: 12px; background:#111827; color:#fff; text-decoration:none; }}
    footer {{ margin-top: 18px; color:#6b7280; font-size: 13px; }}
    h1 {{ margin-top: 0; }}
    code {{ background:#f3f4f6; padding: 2px 6px; border-radius: 8px; }}
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
  <footer>
    <div>Продавец: {SELLER["name"]}. Контакты: {SELLER["email"]}, {SELLER["telegram"]}</div>
    <div class="muted">Услуга цифровая: генерация промо-материалов (видео/тексты) для музыкантов. Оплата через YooKassa.</div>
  </footer>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def site_home() -> str:
    return _page("HypePack — промо-видео для треков", f"""
<h1>HypePack</h1>
<p><span class="pill">музыкантам</span><span class="pill">вертикальные видео</span><span class="pill">пакет под шорты</span></p>

<p>Сервис генерирует пакет вертикальных видео для продвижения трека на площадках коротких роликов.
Вы получаете: видео + готовые заголовки/описания/хештеги + инструкции публикации.</p>

<ul>
  <li><b>Без дистрибуции</b>: мы не публикуем трек и не “выводим в чарты”. Вы публикуете ролики сами.</li>
  <li><b>Лицо — только ваше</b>: при заказе вы подтверждаете, что загружаете свои фото и имеете права на контент.</li>
  <li><b>SLA</b>: обычно результат готов {SLA_TEXT} (в зависимости от нагрузки и очереди задач).</li>
  <li><b>Хранение</b>: исходники и результаты храним {FILES_TTL_DAYS} дней после выдачи, затем удаляем.</li>
</ul>

<p><a class="btn" href="/pricing">Посмотреть тарифы</a></p>
<p class="muted">Для оформления заказа нужен личный кабинет (регистрация и подтверждение email).</p>
""")


@app.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def site_pricing() -> str:
    return _page("Тарифы — HypePack", """
<h1>Тарифы</h1>
<p>Оплата единая за услугу. После оплаты вы проходите этапы: загрузка фото → выбор стилей → подтверждение фотосессии → загрузка видео-референсов → генерация → скачивание архива.</p>

<ul>
  <li><b>Тест</b>: 1 видео</li>
  <li><b>Пакет</b>: 30 видео (1/день на месяц)</li>
  <li><b>Пакет</b>: 90 видео (3/день на месяц)</li>
</ul>

<p class="muted">
Итоговая стоимость может зависеть от текущей себестоимости генераций (мы держим цену не ниже 2× себестоимости).
Точная цена отображается перед оплатой в личном кабинете.
</p>
""")


@app.get("/how", response_class=HTMLResponse, include_in_schema=False)
async def site_how() -> str:
    return _page("Как работает — HypePack", f"""
<h1>Как оказывается услуга</h1>
<ol>
  <li><b>Регистрация</b> и подтверждение email.</li>
  <li><b>Оплата</b> выбранного тарифа.</li>
  <li><b>Загрузка ваших фото</b> → обучение/сохранение профиля лица (можно использовать повторно).</li>
  <li><b>Выбор стилей</b> (до 5) → генерация фотосессии → вы выбираете/перегенерируете кадры до подтверждения.</li>
  <li><b>Загрузка видео-референсов</b> (до 30 сек, обычное качество) → генерация видео.</li>
  <li><b>Получение результата</b>: скачивание поштучно и архивом. В архиве: видео + тексты + инструкции.</li>
</ol>

<h2>Сроки</h2>
<p>Обычно выдаём результат <b>{SLA_TEXT}</b>. В редких случаях дольше из-за очереди или ограничений провайдера генерации.</p>

<h2>Правила по контенту и лицу</h2>
<ul>
  <li>Разрешены только фото/видео с вашим лицом или с лицом человека, который дал явное согласие.</li>
  <li>Пользователь подтверждает права на аудио/видео и законность использования материалов.</li>
</ul>

<p class="muted">Файлы храним {FILES_TTL_DAYS} дней после выдачи результата, потом удаляем автоматически.</p>
""")


@app.get("/contacts", response_class=HTMLResponse, include_in_schema=False)
async def site_contacts() -> str:
    return _page("Контакты — HypePack", f"""
<h1>Контакты</h1>
<p>Email поддержки: <b>{SELLER["email"]}</b></p>
<p>Telegram: <b>{SELLER["telegram"]}</b></p>

<h2>Реквизиты продавца</h2>
<ul>
  <li><b>Продавец</b>: {SELLER["name"]}</li>
  <li><b>ИНН</b>: {SELLER["inn"]} <span class="muted">(обязательно заполнить)</span></li>
  <li><b>ОГРНИП</b>: {SELLER["ogrnip"]} <span class="muted">(обязательно заполнить)</span></li>
  <li><b>Адрес</b>: {SELLER["address"]} <span class="muted">(обязательно заполнить)</span></li>
</ul>
<p class="muted">Без реальных реквизитов YooKassa может не подключить магазин.</p>
""")


@app.get("/legal/offer", response_class=HTMLResponse, include_in_schema=False)
async def legal_offer() -> str:
    return _page("Публичная оферта — HypePack", f"""
<h1>Публичная оферта</h1>
<p class="muted">Редакция от: {__import__("datetime").date.today().isoformat()}</p>

<h2>1. Термины</h2>
<ul>
  <li><b>Исполнитель</b> — {SELLER["name"]}.</li>
  <li><b>Заказчик</b> — пользователь сайта, оплативший услугу.</li>
  <li><b>Услуга</b> — цифровая услуга по генерации промо-материалов для музыкального трека: вертикальные видео, тексты (заголовки/описания/хештеги) и инструкции публикации.</li>
</ul>

<h2>2. Предмет</h2>
<p>Исполнитель оказывает Заказчику услугу по генерации промо-материалов на основании данных, предоставленных Заказчиком (фото/видео-референсы/описание трека).</p>
<p>Исполнитель <b>не</b> осуществляет дистрибуцию трека и <b>не</b> публикует ролики на площадках — Заказчик публикует самостоятельно.</p>

<h2>3. Порядок оказания</h2>
<ol>
  <li>Заказчик проходит регистрацию и подтверждает email.</li>
  <li>Заказчик оплачивает тариф.</li>
  <li>Заказчик загружает фото (лицо) и подтверждает, что имеет право на использование материалов и согласие на использование лица.</li>
  <li>Заказчик выбирает стили и подтверждает результаты фотосессии (выбор/перегенерация).</li>
  <li>Заказчик загружает видео-референсы, Исполнитель генерирует видео.</li>
  <li>Результат предоставляется в личном кабинете для скачивания поштучно и архивом.</li>
</ol>

<h2>4. Сроки</h2>
<p>Ориентировочный срок оказания услуги — <b>{SLA_TEXT}</b> с момента оплаты и предоставления исходных материалов. Срок может увеличиться при высокой нагрузке, сбоях у провайдеров генерации или нарушении требований к исходным файлам.</p>

<h2>5. Права, гарантии и ограничения</h2>
<ul>
  <li>Заказчик гарантирует, что загружает материалы, на которые у него есть права, и что лицо на фото/видео принадлежит Заказчику либо имеется явное согласие владельца лица.</li>
  <li>Запрещена загрузка чужих лиц/контента без согласия правообладателя.</li>
  <li>Исполнитель вправе отказать в оказании услуги при выявлении нарушений правил или требований законодательства.</li>
</ul>

<h2>6. Стоимость и оплата</h2>
<p>Стоимость определяется выбранным тарифом и отображается перед оплатой. Оплата производится через YooKassa. Моментом оплаты считается подтверждение платежа платёжным сервисом.</p>

<h2>7. Возвраты</h2>
<p>Условия возвратов и отмены описаны в разделе <a href="/legal/refund">«Возвраты»</a> и являются частью оферты.</p>

<h2>8. Хранение и выдача результата</h2>
<p>Результаты и исходные файлы доступны для скачивания в течение <b>{FILES_TTL_DAYS} дней</b> после выдачи результата. По истечении срока файлы удаляются автоматически.</p>

<h2>9. Контакты и реквизиты</h2>
<p>Контакты: {SELLER["email"]}, {SELLER["telegram"]}. Реквизиты — на странице <a href="/contacts">Контакты</a>.</p>

<p class="muted">Внимание: оферта — базовый шаблон. Для идеального соответствия вашей модели и требованиям лучше юридическая проверка.</p>
""")


@app.get("/legal/privacy", response_class=HTMLResponse, include_in_schema=False)
async def legal_privacy() -> str:
    return _page("Политика обработки персональных данных — HypePack", f"""
<h1>Политика обработки персональных данных</h1>
<p class="muted">Оператор ПД: {SELLER["name"]}</p>

<h2>1. Какие данные обрабатываем</h2>
<ul>
  <li>email и данные аккаунта</li>
  <li>загружаемые файлы: фото/видео-референсы</li>
  <li>технические данные (IP, cookies, логи) — для безопасности и работы сервиса</li>
</ul>

<h2>2. Цели обработки</h2>
<ul>
  <li>регистрация и авторизация</li>
  <li>оказание услуги (генерация промо-материалов)</li>
  <li>поддержка пользователей</li>
  <li>безопасность, предотвращение злоупотреблений и ведение аудита</li>
</ul>

<h2>3. Основание</h2>
<p>Обработка осуществляется на основании согласия пользователя и необходимости исполнения договора (оказания услуги) после оплаты.</p>

<h2>4. Передача третьим лицам</h2>
<p>Для работы сервиса могут использоваться подрядчики/сервисы инфраструктуры (хостинг, хранение файлов, почта) и сервисы генерации контента. Передача производится в минимально необходимом объёме.</p>

<h2>5. Сроки хранения</h2>
<p>Файлы и результаты храним <b>{FILES_TTL_DAYS} дней</b> после выдачи результата, затем удаляем. Данные аккаунта и платежей храним в срок, необходимый для исполнения обязательств и учёта.</p>

<h2>6. Права пользователя</h2>
<p>Пользователь может запросить удаление аккаунта и данных, написав на {SELLER["email"]}.</p>

<h2>7. Контакты оператора</h2>
<p>Email: <b>{SELLER["email"]}</b>. Telegram: <b>{SELLER["telegram"]}</b>.</p>
""")


@app.get("/legal/refund", response_class=HTMLResponse, include_in_schema=False)
async def legal_refund() -> str:
    return _page("Возвраты и отмена — HypePack", f"""
<h1>Возвраты и отмена</h1>

<h2>1. До запуска генерации</h2>
<p>Если услуга ещё не была запущена (генерация не стартовала), возможна отмена заказа по запросу в поддержку: {SELLER["email"]}.</p>

<h2>2. После запуска генерации</h2>
<p>Если генерация запущена, услуга считается оказываемой. В этом случае возврат возможен только при доказанной технической невозможности оказания услуги по вине Исполнителя.</p>

<h2>3. Если результат не устроил</h2>
<p>Если качество результата не соответствует ожидаемому, мы предлагаем повторную попытку генерации в рамках разумных лимитов тарифа (без гарантии конкретного художественного результата).</p>

<h2>4. Способ обращения</h2>
<p>Для вопросов/заявок: {SELLER["email"]}, {SELLER["telegram"]}.</p>

<p class="muted">Условия возврата цифровых услуг зависят от факта начала оказания услуги. Точные формулировки лучше согласовать с юристом под вашу модель.</p>
""")
