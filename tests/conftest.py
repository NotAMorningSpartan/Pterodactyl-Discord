import pytest
import pytest_asyncio

from bot.config import Settings
from bot.pterodactyl.client import PterodactylClient

PANEL_URL = "https://panel.test"
APP_API_KEY = "app-key"
CLIENT_API_KEY = "client-key"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        discord_token="discord-token",
        discord_guild_id=1,
        allowed_role_id=2,
        pterodactyl_url=PANEL_URL,
        pterodactyl_app_api_key=APP_API_KEY,
        pterodactyl_client_api_key=CLIENT_API_KEY,
    )


@pytest_asyncio.fixture
async def client(settings: Settings):
    async with PterodactylClient(settings) as c:
        yield c
