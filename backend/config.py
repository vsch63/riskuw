"""
backend/config.py
──────────────────
Single source of truth for all environment-driven configuration.
Imported as:  from config import cfg
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "postgresql://uw_user:password@localhost:5432/riskuw"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # ── JWT ───────────────────────────────────────────────────────
    jwt_secret: str = "CHANGE_ME_USE_SECRETS_TOKEN_HEX_32"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # ── App ───────────────────────────────────────────────────────
    environment: str = "development"
    platform_name: str = "RiskUW"
    api_base: str = "http://localhost:8000"
    log_level: str = "INFO"

    # ── Tenant ───────────────────────────────────────────────────
    default_tenant_id: str = ""

    # ── SMTP ─────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    smtp_from: str = "noreply@riskuw.online"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def log_startup_summary(self) -> None:
        logger = logging.getLogger("uw_platform")
        logger.info(
            "RiskUW starting",
            extra={
                "env":       self.environment,
                "db_pool":   f"{self.db_pool_min}–{self.db_pool_max}",
                "log_level": self.log_level,
            },
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


cfg = get_settings()
