"""Конфигурация ботов. Секреты — в bots/.env (gitignore)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV = str(Path(__file__).resolve().parents[1] / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV, extra="ignore", case_sensitive=False)

    tg_bot_token: str
    # Токен MAX-бота (мессенджер MAX). Обязателен только для запуска MAX-канала.
    max_bot_token: str | None = None
    # Публичное имя MAX-бота (username) — нужно для кнопки OpenApp (мини-приложение).
    max_bot_username: str | None = None
    # Единый backend обслуживает все платформы.
    backend_url: str = "http://localhost:8000/api/v1"
    # Публичный HTTPS-URL мини-приложения (Telegram WebApp требует HTTPS).
    webapp_url: str | None = None
    redis_url: str = "redis://localhost:6379/1"


settings = Settings()
