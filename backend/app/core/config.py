from __future__ import annotations

from pydantic import Field
from pydantic.aliases import AliasChoices as AC
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    # Render часто отдаёт postgres://...
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    # переводим на asyncpg, чтобы НЕ нужен был psycopg2
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]

    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field(default="dev", validation_alias=AC("ENV", "env"))
    app_domain: str = Field(default="DOMAIN", validation_alias=AC("DOMAIN", "APP_DOMAIN", "app_domain"))

    database_url: str = Field(validation_alias=AC("DATABASE_URL", "database_url"))
    jwt_secret: str = Field(validation_alias=AC("JWT_SECRET", "jwt_secret"))

    admin_bootstrap_token: str | None = Field(default=None, validation_alias=AC("ADMIN_BOOTSTRAP_TOKEN"))

    # YooKassa
    yookassa_shop_id: str | None = Field(default=None, validation_alias=AC("YOOKASSA_SHOP_ID"))
    yookassa_secret_key: str | None = Field(default=None, validation_alias=AC("YOOKASSA_SECRET_KEY"))
    yookassa_return_url: str | None = Field(default=None, validation_alias=AC("YOOKASSA_RETURN_URL"))
    yookassa_api_base: str = Field(default="https://api.yookassa.ru/v3", validation_alias=AC("YOOKASSA_API_BASE"))

    # Экономика (временно можно оставить None и включить позже)
    cost_image_rub: float | None = Field(default=None, validation_alias=AC("COST_IMAGE_RUB"))
    cost_video_rub: float | None = Field(default=None, validation_alias=AC("COST_VIDEO_RUB"))
    cost_training_rub: float | None = Field(default=None, validation_alias=AC("COST_TRAINING_RUB"))
    min_price_multiplier: float = Field(default=2.0, validation_alias=AC("MIN_PRICE_MULTIPLIER"))

    access_token_minutes: int = Field(default=60, validation_alias=AC("ACCESS_TOKEN_MINUTES"))
    refresh_token_days: int = Field(default=30, validation_alias=AC("REFRESH_TOKEN_DAYS"))
    max_identities_per_user: int = Field(default=3, validation_alias=AC("MAX_IDENTITIES_PER_USER"))

    @property
    def db_url(self) -> str:
        return normalize_database_url(self.database_url)


settings = Settings()
