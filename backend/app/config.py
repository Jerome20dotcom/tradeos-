from functools import lru_cache

from psycopg.conninfo import make_conninfo
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables or the .env file. No secrets live in code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "production"  # development | test | production
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_admin_user: str = "postgres"
    pg_admin_password: str = ""
    pg_app_user: str = "tradeos_app"
    pg_app_password: str = ""
    database_url: str = ""
    db_name: str = "tradeos"
    test_db_name: str = "tradeos_test"
    jwt_secret: str
    jwt_audience: str = "tradeos"
    public_base_url: str = "http://127.0.0.1:8000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    copilot_api_key: str = ""
    copilot_base_url: str = "https://api.openai.com/v1"
    copilot_model: str = "gpt-4o-mini"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @property
    def active_db(self) -> str:
        return self.test_db_name if self.environment == "test" else self.db_name

    @property
    def email_configured(self) -> bool:
        secure_base_url = self.public_base_url.startswith("https://")
        local_base_url = self.environment in {"development", "test"} and self.public_base_url.startswith("http://")
        return bool(self.smtp_host and self.smtp_sender and (secure_base_url or local_base_url))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def app_dsn(db: str | None = None) -> str:
    """Connection for the restricted application role. Row-level security applies to it."""
    s = get_settings()
    if s.database_url:
        return make_conninfo(s.database_url, dbname=db) if db else make_conninfo(s.database_url)
    return make_conninfo(host=s.pg_host, port=s.pg_port, dbname=db or s.active_db,
                         user=s.pg_app_user, password=s.pg_app_password)


def admin_dsn(db: str) -> str:
    """Connection for the database owner. Used only by setup scripts and test cleanup, never by the API."""
    s = get_settings()
    if s.database_url:
        return make_conninfo(s.database_url, dbname=db)
    if not s.pg_admin_password:
        raise ValueError("PG_ADMIN_PASSWORD is required for database setup and migration commands")
    return make_conninfo(host=s.pg_host, port=s.pg_port, dbname=db,
                         user=s.pg_admin_user, password=s.pg_admin_password)
