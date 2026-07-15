"""Конфигурация приложения из переменных окружения (см. infra/.env.example)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "local"
    log_level: str = "INFO"
    sentry_dsn: str | None = None

    # Каталог собранного мини-приложения (SPA). Если задан и существует — backend
    # отдаёт фронт с того же домена, что и API (same-origin, без CORS).
    webroot: str | None = None
    # Каталог собранной админки (SPA). Отдаётся по пути /admin того же домена.
    webroot_admin: str | None = None
    # Папка загруженных медиа (фото каталога). Отдаётся по пути /media, доступна
    # на запись (в отличие от webroot). См. эндпоинт admin/media.py.
    media_root: str = "/app/media"

    # PostgreSQL
    postgres_user: str = "casetop"
    postgres_password: str = "change_me"
    postgres_db: str = "casetop"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # Безопасность AdminUI
    jwt_secret: str = "change_me"
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 14

    # Яндекс Диск
    yandex_disk_oauth_token: str | None = None
    yandex_disk_root: str = "/chechlii/orders"

    # Боты
    tg_bot_token: str | None = None
    max_bot_token: str | None = None

    # Оплата (R3 — выбор шлюза до Спринта 4)
    payment_gateway_tg: str | None = None
    payment_gateway_max: str | None = None

    # Отмена и напоминания
    payment_reminders_minutes: str = "5,45,180,1440"
    order_autocancel_hours: int = 72

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Синхронный URL для Alembic-миграций."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def reminder_offsets_minutes(self) -> list[int]:
        return [int(x) for x in self.payment_reminders_minutes.split(",") if x.strip()]


settings = Settings()
