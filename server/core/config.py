from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Booky Voice Agent"
    
    # DB settings (We default to a postgresql URL, can be overridden by .env)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/booky"

    # Twilio Setings
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None

    # OpenAI Settings
    OPENAI_API_KEY: Optional[str] = None
    
    # Internal auth simple token (for basic CRUD protection)
    API_SECRET_TOKEN: str = "booky-secret-token"
    
    # Django Base URL for tools
    DJANGO_API_BASE_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
