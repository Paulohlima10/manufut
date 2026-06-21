from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Manu Fut API"
    allowed_origins: str = "http://localhost:5173"
    turn_seconds: int = 30
    reconnect_seconds: int = 45
    max_force: float = 1.0
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    dev_auth: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

