from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Booky Voice Agent"
    
    # DB settings (We default to a postgresql URL, can be overridden by .env)
    DATABASE_URL: str
    
    # Twilio Setings
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None

    # OpenAI Settings
    OPENAI_API_KEY: Optional[str] = None
    
    # Internal auth simple token (for basic CRUD protection)
    API_SECRET_TOKEN: str

    # CORS settings
    ALLOWED_ORIGINS: list[str] = ["*"] # Default to * for dev, override in .env

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
