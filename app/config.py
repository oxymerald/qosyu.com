import secrets
import warnings

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Окружение ---
    ENVIRONMENT: str = "development"  # development | production

    # --- Хранилища ---
    DATABASE_URL: str = "postgresql+asyncpg://qosyu:qosyu@localhost:5432/qosyu"
    REDIS_URL: str = "redis://localhost:6379/0"

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
    # --- AI (Claude) ---
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-opus-4-8"
    # --- Пилотная зона (депо переработчика по умолчанию) ---
    DEPOT_LAT: float = 47.1167  # Атырау
    DEPOT_LON: float = 51.8833
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_EMAIL: str = "info@qosyu.kz"

    # --- Первичный администратор (создаётся при старте, если задан) ---
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    class Config:
        env_file = ".env"

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
