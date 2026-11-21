import secrets
import warnings
from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Окружение ---
    ENVIRONMENT: str = "development"  # development | production

    # --- Хранилища ---
    DATABASE_URL: str = "postgresql+asyncpg://qosyu:qosyu@localhost:5432/qosyu"
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_SCHEMA: str = Field(default="public", pattern=r"^[a-z][a-z0-9_]{0,62}$")
    DATABASE_SSL: bool = False
    DATABASE_SSL_CA_FILE: str = ""
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=20)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0, le=20)

    # --- Безопасность ---
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12 часов
    # Список origin'ов через запятую. Пустая строка = фронтенд только с того же origin.
    ALLOWED_ORIGINS: str = ""
    # Список хостов через запятую, "*" = любой (для разработки).
    ALLOWED_HOSTS: str = "*"
    MAX_BODY_SIZE: int = 1_000_000  # 1 МБ на запрос

    # --- Интеграции ---
    # Публичный демо-сервер OSRM: работает из коробки. Для production —
    # свой OSRM-инстанс или OpenRouteService (см. README).
    OSRM_BASE_URL: str = "https://router.project-osrm.org"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    # --- AI (Gemini) ---
    AI_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    DGIS_API_KEY: str = ""
    DGIS_MATRIX_ENABLED: bool = True
    DGIS_MATRIX_DAILY_REQUESTS: int = 24  # Each request: at most 9 x 9 billed cells.
    # --- Пилотная зона (депо переработчика по умолчанию) ---
    DEPOT_LAT: float = 47.1167  # Атырау
    DEPOT_LON: float = 51.8833

    # --- Первичный администратор (создаётся при старте, если задан) ---
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # Public contact fields are optional.
    CONTACT_LOCATION: str = ""
    CONTACT_LOCATION_EN: str = ""
    CONTACT_LOCATION_KK: str = ""
    CONTACT_PHONE: str = Field(default="", pattern=r"^(\+?[0-9][0-9 ()-]{5,23}[0-9])?$")
    CONTACT_EMAIL: EmailStr | Literal[""] = ""
    CONTACT_INSTAGRAM: str = Field(default="", pattern=r"^(@?[A-Za-z0-9_.]{1,30})?$")
    CONTACT_TIKTOK: str = Field(default="", pattern=r"^(@?[A-Za-z0-9_.]{1,24})?$")
    CONTACT_TELEGRAM: str = Field(default="", pattern=r"^(@[A-Za-z0-9_]{5,32})?$")
    CONTACT_WHATSAPP: str = Field(default="", pattern=r"^(\+?[0-9]{7,15})?$")

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[1] / ".env", ".env"),
        env_file_encoding="utf-8",
        # The shared file also contains Compose variables such as POSTGRES_DB.
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()] or ["*"]


settings = Settings()

if not settings.SECRET_KEY:
    if settings.is_production:
        raise RuntimeError(
            "SECRET_KEY не задан. В production задайте SECRET_KEY в окружении "
            "(например: python -c \"import secrets; print(secrets.token_urlsafe(64))\")."
        )
    # В разработке генерируем одноразовый ключ: токены живут до перезапуска.
    settings.SECRET_KEY = secrets.token_urlsafe(64)
    warnings.warn("SECRET_KEY не задан — сгенерирован временный ключ для разработки.")
