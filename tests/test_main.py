from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from bot.main import PterodactylBot


def make_bot() -> PterodactylBot:
    settings = SimpleNamespace(discord_guild_id=123456789)
    return PterodactylBot(settings)


def make_forbidden() -> discord.Forbidden:
    response = SimpleNamespace(status=403, reason="Forbidden")
    return discord.Forbidden(response, {"code": 50001, "message": "Missing Access"})


async def test_setup_hook_logs_actionable_message_on_forbidden_sync(caplog):
    bot = make_bot()
    bot.load_extension = AsyncMock()
    bot.tree.copy_global_to = lambda **kwargs: None
    bot.tree.sync = AsyncMock(side_effect=make_forbidden())

    with caplog.at_level("ERROR", logger="bot"):
        with pytest.raises(discord.Forbidden):
            await bot.setup_hook()

    messages = [record.getMessage() for record in caplog.records]
    assert any("applications.commands" in msg for msg in messages)
    assert any(str(bot.settings.discord_guild_id) in msg for msg in messages)


async def test_setup_hook_logs_success_on_normal_sync():
    bot = make_bot()
    bot.load_extension = AsyncMock()
    bot.tree.copy_global_to = lambda **kwargs: None
    bot.tree.sync = AsyncMock(return_value=[SimpleNamespace(), SimpleNamespace()])

    await bot.setup_hook()

    bot.tree.sync.assert_awaited_once()
