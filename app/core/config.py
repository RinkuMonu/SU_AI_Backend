from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    NODE_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"
    PORT: int = 8000

    MONGO_URI: str = "mongodb+srv://rinkuyadav9460_db_user:PJrNGHmujot6YovI@cluster0.wrmtwnk.mongodb.net/"
    DATABASE_NAME: str = "sevenunique_ai_db"

    JWT_SECRET_KEY: Optional[str] = "development-secret-key-unsafe"
    JWT_ACCESS_SECRET: str = "development_access_secret"
    JWT_REFRESH_SECRET: str = "development_refresh_secret"
    TOKEN_ENCRYPTION_KEY: str = "development_encryption_key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    AI_PROVIDER: str = "mock"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.1-70b-versatile"

    FASHION_IMAGE_PROVIDER: str = "pollinations"
    FASHION_IMAGE_API_KEY: str | None = None
    VIRTUAL_TRYON_PROVIDER: str = ""
    VIRTUAL_TRYON_API_KEY: str | None = None

    INSTAGRAM_APP_ID: str | None = None
    INSTAGRAM_APP_SECRET: str | None = None
    INSTAGRAM_API_VERSION: str = "v21.0"
    INSTAGRAM_REDIRECT_URI: str = "http://localhost:8000/api/instagram/callback"

    FACEBOOK_APP_ID: str | None = None
    FACEBOOK_APP_SECRET: str | None = None
    FACEBOOK_REDIRECT_URI: str = "http://localhost:8000/api/facebook/callback"
    BACKEND_URL: str = "http://localhost:8000"

    SMTP_HOST: str | None = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str = "noreply@dhandagrow.com"
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_FROM: str | None = None

    PAYIN_URL: str = ""
    PAYIN_TOKEN: str = ""
    
    GEOAPIFY_API_KEY: str = ""

    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def resolve_smtp_settings(self):
        if not self.SMTP_USERNAME and self.SMTP_USER:
            self.SMTP_USERNAME = self.SMTP_USER
        if not self.SMTP_PASSWORD and self.SMTP_PASS:
            self.SMTP_PASSWORD = self.SMTP_PASS.replace(" ", "")
        elif self.SMTP_PASSWORD:
            self.SMTP_PASSWORD = self.SMTP_PASSWORD.replace(" ", "")
        if self.SMTP_FROM:
            self.SMTP_FROM_EMAIL = self.SMTP_FROM
        elif self.SMTP_USERNAME and self.SMTP_FROM_EMAIL == "noreply@dhandagrow.com":
            self.SMTP_FROM_EMAIL = self.SMTP_USERNAME
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
