from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path
import os


load_dotenv()


class Settings(BaseSettings):
    app_name: str = "DPP Guard API"
    debug: bool = False
    database_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: str = ""
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 60 * 24 * 7
    allowed_hosts: str = ""
    static_dir: Path = Path(__file__).parent.parent.parent / "static"
    public_url: str = "http://localhost:8000"


settings = Settings()

if not settings.secret_key:
    raise RuntimeError("Secret key not configured.")


os.makedirs(settings.static_dir, exist_ok=True)
