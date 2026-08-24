from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_token: str
    discord_guild_id: int
    allowed_role_id: int

    pterodactyl_url: str
    pterodactyl_app_api_key: str
    pterodactyl_client_api_key: str

    log_level: str = "INFO"
