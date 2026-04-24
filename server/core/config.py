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
    ALLOWED_ORIGINS: list[str] = [
        "https://booky-ai.com",
        "https://www.booky-ai.com",
        "https://bookyai.co.uk",
        "https://www.bookyai.co.uk",
        "https://staging.booky-ai.com",
        "https://staging.bookyai.co.uk",
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000"
    ]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
