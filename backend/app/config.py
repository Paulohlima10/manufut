from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # project root (.env)


class Settings(BaseSettings):
    app_name: str = "Manu Fut API"
    allowed_origins: str = "http://localhost:5173"
    # Front e API no Render usam subdomínios diferentes (ex.: manufut vs manufut-1).
    allowed_origin_regex: str = r"https://.*\.onrender\.com"
    turn_seconds: int = 30
    match_turns: int = 40
    reconnect_seconds: int = 45
    max_force: float = 1.0
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    room_store_path: Path = ROOT_DIR / ".data" / "rooms.json"
    dev_auth: bool = False
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @field_validator("room_store_path", mode="before")
    @classmethod
    def resolve_room_store_path(cls, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT_DIR / path


settings = Settings()
