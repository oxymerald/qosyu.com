from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200
    OSRM_BASE_URL: str = "http://osrm:5000"
    GOOGLE_MAPS_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
