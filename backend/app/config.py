from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
	APP_ENV: str = "development"
	APP_SECRET: str = "change_me"

	# Database
	DATABASE_URL: Optional[str] = None
	SQLITE_URL: str = "sqlite+aiosqlite:///./dev.db"

	# LLM (Gemini only)
	GEMINI_API_KEY: Optional[str] = None
	GEMINI_MODEL: str = "gemini-2.5-flash"

	# Google
	GOOGLE_CLIENT_ID: Optional[str] = None
	GOOGLE_CLIENT_SECRET: Optional[str] = None
	GOOGLE_REFRESH_TOKEN: Optional[str] = None
	GOOGLE_CALENDAR_ID: Optional[str] = None

	# Email (SMTP)
	SMTP_HOST: Optional[str] = None
	SMTP_PORT: int = 587
	SMTP_USER: Optional[str] = None
	SMTP_PASSWORD: Optional[str] = None
	FROM_EMAIL: Optional[str] = None

	# Slack
	SLACK_BOT_TOKEN: Optional[str] = None
	SLACK_CHANNEL_ID: Optional[str] = None

	model_config = SettingsConfigDict(env_file="backend/.env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
	return Settings() 