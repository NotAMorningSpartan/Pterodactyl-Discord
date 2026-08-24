from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import httpx

from bot.cogs.power import (
    API_ERROR_MESSAGE,
    UNREACHABLE_MESSAGE,
    PowerCog,
    ServerListPaginator,
    build_server_embeds,
)
from bot.pterodactyl.client import PterodactylAPIError
from bot.pterodactyl.models import Server


def make_servers(count: int) -> list[Server]:
    return [
        Server(id=i, identifier=f"srv{i:03d}", name=f"Server {i}", node=(i % 3) + 1)
        for i in range(1, count + 1)
    ]


def make_cog() -> PowerCog:
    cog = PowerCog.__new__(PowerCog)
    cog.bot = SimpleNamespace()
    cog.client = AsyncMock()
    return cog


def make_interaction() -> AsyncMock:
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user = SimpleNamespace(id=42)
    return interaction


def test_build_server_embeds_single_page_has_no_footer():
    embeds = build_server_embeds(make_servers(5))

    assert len(embeds) == 1
    assert len(embeds[0].fields) == 5
    assert embeds[0].footer.text is None
    assert embeds[0].fields[0].name == "Server 1"
    value = embeds[0].fields[0].value
    assert "srv001" in value
    assert "2" in value


def test_build_server_embeds_paginates_past_twenty():
    embeds = build_server_embeds(make_servers(25))

    assert len(embeds) == 2
    assert len(embeds[0].fields) == 20
    assert len(embeds[1].fields) == 5
    assert embeds[0].footer.text == "Page 1/2"
    assert embeds[1].footer.text == "Page 2/2"


async def test_servers_command_replies_with_embed_on_success():
    cog = make_cog()
    cog.client.list_servers.return_value = make_servers(3)
    interaction = make_interaction()

    await PowerCog.servers.callback(cog, interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.edit_original_response.assert_awaited_once()
    _, kwargs = interaction.edit_original_response.call_args
    assert isinstance(kwargs["embed"], discord.Embed)
    assert "view" not in kwargs


async def test_servers_command_starts_paginator_for_many_servers():
    cog = make_cog()
    cog.client.list_servers.return_value = make_servers(25)
    interaction = make_interaction()

    await PowerCog.servers.callback(cog, interaction)

    _, kwargs = interaction.edit_original_response.call_args
    assert isinstance(kwargs["view"], ServerListPaginator)
    assert len(kwargs["view"].embeds) == 2


async def test_servers_command_reports_clean_message_when_api_unreachable():
    cog = make_cog()
    cog.client.list_servers.side_effect = httpx.ConnectError("connection refused")
    interaction = make_interaction()

    await PowerCog.servers.callback(cog, interaction)

    interaction.edit_original_response.assert_awaited_once_with(content=UNREACHABLE_MESSAGE)


async def test_servers_command_reports_clean_message_on_api_error():
    cog = make_cog()
    cog.client.list_servers.side_effect = PterodactylAPIError("list_servers", 500, "Server Error")
    interaction = make_interaction()

    await PowerCog.servers.callback(cog, interaction)

    interaction.edit_original_response.assert_awaited_once_with(content=API_ERROR_MESSAGE)


async def test_servers_command_reports_no_servers_found():
    cog = make_cog()
    cog.client.list_servers.return_value = []
    interaction = make_interaction()

    await PowerCog.servers.callback(cog, interaction)

    interaction.edit_original_response.assert_awaited_once_with(content="No servers found.")
