from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "change-me-dev-only-secret-change-me-dev-only-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    jwt_secret: str = DEV_SECRET
    jwt_issuer: str = "kaamsetu-api"
    jwt_audience: str = "kaamsetu-app"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    database_url: str = "sqlite:///./kaamsetu.db"
    frontend_origins: str = "http://localhost:5173"
    allowed_hosts: str = "localhost,127.0.0.1"

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    redis_url: str = ""

    # Login protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def hosts(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def _secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.jwt_secret == DEV_SECRET:
        raise RuntimeError("Refusing to start: set a real JWT_SECRET in production")
    return s
