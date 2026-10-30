import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    NODE_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001,http://localhost:5173,http://127.0.0.1:5173,https://dhandagrow.com,https://www.dhandagrow.com,https://api.dhandagrow.com"
    PORT: int = 8000

    MONGO_URI: str = "mongodb+srv://rinkuyadav9460_db_user:PJrNGHmujot6YovI@cluster0.wrmtwnk.mongodb.net/"
    DATABASE_NAME: str = "sevenunique_ai_db"

    JWT_SECRET_KEY: Optional[str] = "development-secret-key-unsafe"
    JWT_ACCESS_SECRET: str = "development_access_secret"
    JWT_REFRESH_SECRET: str = "development_refresh_secret"
    TOKEN_ENCRYPTION_KEY: str = "development_encryption_key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 365 * 5  # 5 years (persistent until logout)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 365 * 5  # 5 years

    AI_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-flash-lite-latest"
    GEMINI_VIDEO_MODEL: str = "veo-3.1-fast-generate-preview"
    VIDEO_PROVIDER: str = "veo"
    VOICE_PROVIDER: str = "gtts"
    VIDEO_API_KEY: Optional[str] = None
    IMAGE_API_KEY: Optional[str] = None
    IMAGE_API_URL: Optional[str] = None
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.1-70b-versatile"
    JWT_SECRET: Optional[str] = None
    MONGODB_URI: Optional[str] = None

    FASHION_IMAGE_PROVIDER: str = "gemini"
    FASHION_IMAGE_API_KEY: str | None = None
    VIRTUAL_TRYON_PROVIDER: str = "gemini"
    VIRTUAL_TRYON_API_KEY: str | None = None

    INSTAGRAM_APP_ID: str | None = None
    INSTAGRAM_APP_SECRET: str | None = None
    INSTAGRAM_APPID: str | None = None
    INSTAGRAM_SECTRET: str | None = None
    INSTAGRAM_SECRET: str | None = None
    INSTAGRAM_API_VERSION: str = "v21.0"
    INSTAGRAM_REDIRECT_URI: str = "http://localhost:8000/api/instagram/callback"

    FACEBOOK_APP_ID: str | None = None
    FACEBOOK_APP_SECRET: str | None = None
    FACEBOOK_API_VERSION: str = "v19.0"
    FACEBOOK_REDIRECT_URI: str = "https://api.dhandagrow.com/api/facebook/callback"
    FACEBOOK_SCOPES: str = "public_profile,email,pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish"
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "https://dhandagrow.com/login/user"
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    NEXT_PUBLIC_GOOGLE_CLIENT_ID: Optional[str] = None
    # LinkedIn OAuth
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    Linkedin_client_id: Optional[str] = None
    Linkedin_client_secret: Optional[str] = None
    LINKEDIN_REDIRECT_URI: str = "https://dhandagrow.com/login/user"
    LINKEDIN_SCOPES: str = "openid profile email w_member_social"

    BACKEND_URL: str = "http://localhost:8000"
    NEXT_PUBLIC_API_URL: str | None = None

    CASHFREE_APP_ID: str = ""
    CASHFREE_SECRET_KEY: str = ""
    CASHFREE_ENV: str = "TEST"
    CASHFREE_API_VERSION: str = "2023-08-01"

    PAYIN_URL: str = ""
    PAYIN_TOKEN: str = ""
    
    GEOAPIFY_API_KEY: str = ""

    def get_public_url(self, path: Optional[str]) -> str:
        """Converts a local media path into a fully qualified public URL using BACKEND_URL."""
        if not path:
            return ""
        import re
        base = (self.BACKEND_URL or "https://untapped-petite-shallot.ngrok-free.dev").rstrip("/")
        # If path points to localhost/127.0.0.1, rewrite to public BACKEND_URL
        if "localhost" in path or "127.0.0.1" in path:
            return re.sub(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?", base, path)
        if path.startswith("http://") or path.startswith("https://"):
            return path
        clean_path = path if path.startswith("/") else f"/{path}"
        if base:
            return f"{base}{clean_path}"
        return clean_path

    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def resolve_settings(self):
        # Resolve LinkedIn settings
        if not self.LINKEDIN_CLIENT_ID and self.Linkedin_client_id:
            self.LINKEDIN_CLIENT_ID = self.Linkedin_client_id
        if not self.LINKEDIN_CLIENT_SECRET and self.Linkedin_client_secret:
            self.LINKEDIN_CLIENT_SECRET = self.Linkedin_client_secret

        if self.NEXT_PUBLIC_API_URL and self.BACKEND_URL == "http://localhost:8000":
            self.BACKEND_URL = self.NEXT_PUBLIC_API_URL
        if not self.INSTAGRAM_APP_ID and self.INSTAGRAM_APPID:
            self.INSTAGRAM_APP_ID = self.INSTAGRAM_APPID
        if not self.INSTAGRAM_APP_SECRET and (self.INSTAGRAM_SECTRET or self.INSTAGRAM_SECRET):
            self.INSTAGRAM_APP_SECRET = self.INSTAGRAM_SECTRET or self.INSTAGRAM_SECRET
        if not self.JWT_SECRET_KEY and self.JWT_SECRET:
            self.JWT_SECRET_KEY = self.JWT_SECRET
        if self.JWT_SECRET and self.JWT_ACCESS_SECRET == "development_access_secret":
            self.JWT_ACCESS_SECRET = self.JWT_SECRET
        if not self.GOOGLE_CLIENT_ID:
            self.GOOGLE_CLIENT_ID = self.google_client_id or self.NEXT_PUBLIC_GOOGLE_CLIENT_ID
        if not self.GOOGLE_CLIENT_SECRET and self.google_client_secret:
            self.GOOGLE_CLIENT_SECRET = self.google_client_secret
        if self.MONGODB_URI and (not self.MONGO_URI or self.MONGO_URI == "mongodb://localhost:27017"):
            self.MONGO_URI = self.MONGODB_URI
        return self

    # SMS / Fast2SMS Configuration
    SMS_PROVIDER: str = "fast2sms"
    FAST2SMS_API_KEY: str = "8Ke0teaW2mo5i6yh7A06YzMookM9RjGrTKSsd5AlJEm2gOozuql50GOqKm4e"
    FAST2SMS_OTP_ID: str = ""
    MSG91_AUTH_KEY: str | None = None
    MSG91_TEMPLATE_ID_N_REG: str | None = None
    MSG91_TEMPLATE_ID_FOR_LOG: str | None = None
    MSG91_TEMPLATE_ID_FOR_FORGET_PASWORD: str | None = None
    MSG91_TEMPLATE_ID_FOR_RESET_MPIN: str | None = None

    _backend_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    model_config = SettingsConfigDict(env_file=(_backend_env, ".env"), env_file_encoding="utf-8", extra="ignore")


settings = Settings()
