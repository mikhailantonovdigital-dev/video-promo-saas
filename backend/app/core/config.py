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

    access_token_minutes: int = 60
    refresh_token_days: int = 30

    max_identities_per_user: int = 3

    @property
    def db_url(self) -> str:
        return normalize_database_url(self.database_url)


settings = Settings()
