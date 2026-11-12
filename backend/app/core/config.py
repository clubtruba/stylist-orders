from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_secret: str = "development-secret-change-me-please"
    database_url: str = "postgresql+asyncpg://telegram_orders:development-only@db/telegram_orders"
    telegram_bot_token: str = ""
    telegram_admin_ids: str = ""
    telegram_stylist_ids: str = ""
    business_timezone: str = "Europe/Moscow"
    telegram_webapp_url: str = ""
    telegram_init_data_max_age_seconds: int = 3600
    product_browser_url: str = ""
    payment_proof_dir: str = "/app/payment-proofs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("app_secret")
    @classmethod
    def production_secret_is_not_default(cls, value: str, info):
        if info.data.get("app_env") == "production" and "development" in value:
            raise ValueError("APP_SECRET must be replaced in production")
        return value

    @field_validator("telegram_webapp_url")
    @classmethod
    def production_webapp_uses_https(cls, value: str, info):
        if info.data.get("app_env") == "production" and not value.startswith("https://"):
            raise ValueError("TELEGRAM_WEBAPP_URL must use HTTPS in production")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def telegram_admin_id_set(self) -> set[int]:
        try:
            return {int(value.strip()) for value in self.telegram_admin_ids.split(",") if value.strip()}
        except ValueError as exc:
            raise ValueError("TELEGRAM_ADMIN_IDS must contain comma-separated integers") from exc

    @property
    def telegram_stylist_id_set(self) -> set[int]:
        try:
            return {int(value.strip()) for value in self.telegram_stylist_ids.split(",") if value.strip()}
        except ValueError as exc:
            raise ValueError("TELEGRAM_STYLIST_IDS must contain comma-separated integers") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()
