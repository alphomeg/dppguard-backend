from pydantic_settings import BaseSettings
from dotenv import load_dotenv


load_dotenv()


class Settings(BaseSettings):
    app_name: str = "DPP Guard API"
    debug: bool = False
    database_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: str = ""
    access_token_expire_minutes: int = 15  # 15 mins
    refresh_token_expire_minutes: int = 60 * 60 * 24 * 7  # 7 days


settings = Settings()

if not settings.secret_key:
    raise RuntimeError("Secret key not configured.")
