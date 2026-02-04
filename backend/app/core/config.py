from __future__ import annotations

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    # Render часто даёт postgres://... — приводим к async SQLAlchemy формату
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field(default="dev", validation_alias=AliasChoices("ENV", "env"))
    app_domain: str = Field(default="DOMAIN", validation_alias=AliasChoices("DOMAIN", "APP_DOMAIN", "app_domain"))

    database_url: str = Field(validation_alias=AliasChoices("DATABASE_URL", "database_url"))
    jwt_secret: str = Field(validation_alias=AliasChoices("JWT_SECRET", "jwt_secret"))

    admin_bootstrap_token: str | None = Field(default=None, validation_alias=AliasChoices("ADMIN_BOOTSTRAP_TOKEN"))

    access_token_minutes: int = 60
    refresh_token_days: int = 30

    max_identities_per_user: int = 3

    @property
    def db_url(self) -> str:
        return normalize_database_url(self.database_url)

    from pydantic import Field, AliasChoices

    yookassa_shop_id: str | None = Field(default=None, validation_alias=AliasChoices("YOOKASSA_SHOP_ID"))
    yookassa_secret_key: str | None = Field(default=None, validation_alias=AliasChoices("YOOKASSA_SECRET_KEY"))
    yookassa_return_url: str | None = Field(default=None, validation_alias=AliasChoices("YOOKASSA_RETURN_URL"))
    yookassa_api_base: str = "https://api.yookassa.ru/v3"
    
    cost_image_rub: float | None = Field(default=None, validation_alias=AliasChoices("COST_IMAGE_RUB"))
    cost_video_rub: float | None = Field(default=None, validation_alias=AliasChoices("COST_VIDEO_RUB"))
    cost_training_rub: float | None = Field(default=None, validation_alias=AliasChoices("COST_TRAINING_RUB"))
    min_price_multiplier: float = Field(default=2.0, validation_alias=AliasChoices("MIN_PRICE_MULTIPLIER"))


settings = Settings()
