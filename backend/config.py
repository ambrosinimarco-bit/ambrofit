from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_webhook_url: str = ""

    # Anthropic
    anthropic_api_key: str

    # Groq
    groq_api_key: str

    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_service_key: str

    # Strava
    strava_client_id: str
    strava_client_secret: str
    strava_webhook_verify_token: str = "fitness_tracker_webhook"
    strava_redirect_uri: str

    # App
    app_base_url: str = "http://localhost:8000"
    secret_key: str = "change_me_in_production"
    environment: str = "development"

    # Defaults
    default_user_telegram_id: str = ""
    default_daily_calorie_goal: int = 2200
    default_protein_goal: int = 160
    default_carbs_goal: int = 220
    default_fat_goal: int = 80

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
