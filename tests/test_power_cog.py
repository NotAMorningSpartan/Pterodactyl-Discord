from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import httpx

import bot.cogs.power as power_module
from bot.cogs.power import (
    API_ERROR_MESSAGE,
    UNREACHABLE_MESSAGE,
    KillConfirmView,
    PowerCog,
    ServerListPaginator,
    _format_bytes,
    _format_duration,
    build_server_embeds,
    build_stats_embed,
)
from bot.pterodactyl.client import PterodactylAPIError
from bot.pterodactyl.models import ResourceUsage, Server


def make_usage(**overrides) -> ResourceUsage:
    defaults = dict(
        current_state="running",
        is_suspended=False,
        memory_bytes=536870912,
        memory_limit_bytes=1073741824,
        cpu_absolute=12.5,
        disk_bytes=2147483648,
        disk_limit_bytes=5368709120,
        network_rx_bytes=1024,
        network_tx_bytes=2048,
        uptime=274320000,
    )
    defaults.update(overrides)
    return ResourceUsage(**defaults)


def make_servers(count: int) -> list[Server]:
    return [
        Server(id=i, identifier=f"srv{i:03d}", name=f"Server {i}", node=(i % 3) + 1)
        for i in range(1, count + 1)
    ]


def make_cog() -> PowerCog:
    cog = PowerCog.__new__(PowerCog)
    cog.bot = SimpleNamespace()
    cog.client = AsyncMock()
    cog._server_cache = []
    cog._server_cache_expiry = 0.0
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


# --- /server <action> group ---------------------------------------------------------


async def test_autocomplete_returns_matching_choices():
    cog = make_cog()
    cog.client.list_servers.return_value = make_servers(3)
    interaction = make_interaction()

    choices = await cog._autocomplete_server(interaction, "server 2")

    assert len(choices) == 1
    assert choices[0].value == "srv002"
    assert "Server 2" in choices[0].name


async def test_autocomplete_matches_by_identifier_too():
    cog = make_cog()
    cog.client.list_servers.return_value = make_servers(3)
    interaction = make_interaction()

    choices = await cog._autocomplete_server(interaction, "srv003")

    assert [c.value for c in choices] == ["srv003"]


async def test_autocomplete_caches_within_ttl():
    cog = make_cog()
    cog.client.list_servers.return_value = make_servers(2)
    interaction = make_interaction()

    await cog._autocomplete_server(interaction, "")
    await cog._autocomplete_server(interaction, "")

    cog.client.list_servers.assert_awaited_once()


async def test_autocomplete_returns_empty_list_on_api_failure():
    cog = make_cog()
    cog.client.list_servers.side_effect = httpx.ConnectError("connection refused")
    interaction = make_interaction()

    choices = await cog._autocomplete_server(interaction, "")

    assert choices == []


async def test_start_skips_action_when_already_running():
    cog = make_cog()
    cog.client.get_power_state.return_value = "running"
    interaction = make_interaction()

    await PowerCog.server_start.callback(cog, interaction, "srv001")

    cog.client.send_power_action.assert_not_called()
    interaction.edit_original_response.assert_awaited_with(content="`srv001` is already running.")


async def test_start_sends_action_when_offline():
    cog = make_cog()
    cog.client.get_power_state.return_value = "offline"
    interaction = make_interaction()

    await PowerCog.server_start.callback(cog, interaction, "srv001")

    cog.client.send_power_action.assert_awaited_once_with("srv001", "start")
    interaction.edit_original_response.assert_awaited_with(content="Sent **start** to `srv001`.")


async def test_stop_skips_action_when_already_offline():
    cog = make_cog()
    cog.client.get_power_state.return_value = "offline"
    interaction = make_interaction()

    await PowerCog.server_stop.callback(cog, interaction, "srv001")

    cog.client.send_power_action.assert_not_called()
    interaction.edit_original_response.assert_awaited_with(content="`srv001` is already stopped.")


async def test_restart_never_checks_current_state():
    cog = make_cog()
    interaction = make_interaction()

    await PowerCog.server_restart.callback(cog, interaction, "srv001")

    cog.client.get_power_state.assert_not_called()
    cog.client.send_power_action.assert_awaited_once_with("srv001", "restart")


async def test_power_action_reports_server_not_found():
    cog = make_cog()
    cog.client.send_power_action.side_effect = PterodactylAPIError("srv001", 404, "Not found")
    interaction = make_interaction()

    await PowerCog.server_restart.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_with(
        content="No server found with identifier `srv001`."
    )


async def test_power_action_reports_unreachable_api():
    cog = make_cog()
    cog.client.send_power_action.side_effect = httpx.ConnectError("connection refused")
    interaction = make_interaction()

    await PowerCog.server_restart.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_with(content=UNREACHABLE_MESSAGE)


async def test_power_action_reports_generic_api_error():
    cog = make_cog()
    cog.client.send_power_action.side_effect = PterodactylAPIError("srv001", 500, "boom")
    interaction = make_interaction()

    await PowerCog.server_restart.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_with(content=API_ERROR_MESSAGE)


# --- /server kill confirmation --------------------------------------------------------


async def test_kill_confirm_view_confirm_button_sets_confirmed():
    view = KillConfirmView(author_id=1)
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()

    await view.confirm_button.callback(interaction)

    assert view.confirmed is True
    assert all(item.disabled for item in view.children)
    interaction.response.edit_message.assert_awaited_once()


async def test_kill_confirm_view_cancel_button_leaves_unconfirmed():
    view = KillConfirmView(author_id=1)
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()

    await view.cancel_button.callback(interaction)

    assert view.confirmed is False
    interaction.response.edit_message.assert_awaited_once()


async def test_kill_confirm_view_timeout_leaves_unconfirmed():
    view = KillConfirmView(author_id=1)
    view.confirmed = True

    await view.on_timeout()

    assert view.confirmed is False


def _patch_kill_confirm_view(monkeypatch, *, confirmed: bool) -> AsyncMock:
    fake_view = AsyncMock()
    fake_view.confirmed = confirmed
    fake_view.wait = AsyncMock(return_value=False)
    monkeypatch.setattr(power_module, "KillConfirmView", lambda **kwargs: fake_view)
    return fake_view


async def test_server_kill_shows_confirmation_prompt_first(monkeypatch):
    cog = make_cog()
    interaction = make_interaction()
    _patch_kill_confirm_view(monkeypatch, confirmed=False)

    await PowerCog.server_kill.callback(cog, interaction, "srv001")

    first_call = interaction.edit_original_response.call_args_list[0]
    assert "force-kill" in first_call.kwargs["content"]
    cog.client.send_power_action.assert_not_called()


async def test_server_kill_does_nothing_when_cancelled(monkeypatch):
    cog = make_cog()
    interaction = make_interaction()
    _patch_kill_confirm_view(monkeypatch, confirmed=False)

    await PowerCog.server_kill.callback(cog, interaction, "srv001")

    cog.client.get_power_state.assert_not_called()
    cog.client.send_power_action.assert_not_called()


async def test_server_kill_executes_when_confirmed(monkeypatch):
    cog = make_cog()
    cog.client.get_power_state.return_value = "running"
    interaction = make_interaction()
    _patch_kill_confirm_view(monkeypatch, confirmed=True)

    await PowerCog.server_kill.callback(cog, interaction, "srv001")

    cog.client.send_power_action.assert_awaited_once_with("srv001", "kill")


async def test_server_kill_confirmed_but_already_offline_skips_action(monkeypatch):
    cog = make_cog()
    cog.client.get_power_state.return_value = "offline"
    interaction = make_interaction()
    _patch_kill_confirm_view(monkeypatch, confirmed=True)

    await PowerCog.server_kill.callback(cog, interaction, "srv001")

    cog.client.send_power_action.assert_not_called()
    last_call = interaction.edit_original_response.call_args_list[-1]
    assert "nothing to kill" in last_call.kwargs["content"]


# --- formatting helpers ---------------------------------------------------------------


def test_format_duration_zero_is_seconds():
    assert _format_duration(0) == "0s"


def test_format_duration_under_a_minute():
    assert _format_duration(45_000) == "45s"


def test_format_duration_hours_and_minutes():
    assert _format_duration((62 * 60) * 1000) == "1h 2m"


def test_format_duration_days_hours_minutes():
    ms = ((3 * 86400) + (4 * 3600) + (12 * 60)) * 1000
    assert _format_duration(ms) == "3d 4h 12m"


def test_format_bytes_under_one_kb():
    assert _format_bytes(512) == "512 B"


def test_format_bytes_kb():
    assert _format_bytes(1536) == "1.5 KB"


def test_format_bytes_gb():
    assert _format_bytes(1073741824) == "1.0 GB"


def test_format_bytes_zero():
    assert _format_bytes(0) == "0 B"


# --- stats embed -----------------------------------------------------------------------


def test_stats_embed_running_shows_all_fields():
    usage = make_usage(current_state="running")

    embed = build_stats_embed("srv001", usage)

    field_names = [f.name for f in embed.fields]
    assert field_names == ["State", "Uptime", "Memory", "CPU", "Disk", "Network I/O"]

    fields = {f.name: f.value for f in embed.fields}
    assert fields["State"] == "Running"
    assert fields["Uptime"] == "3d 4h 12m"
    assert fields["Memory"] == "512.0 MB / 1.0 GB"
    assert fields["CPU"] == "12.5%"
    assert fields["Disk"] == "2.0 GB / 5.0 GB"
    assert fields["Network I/O"] == "↓ 1.0 KB / ↑ 2.0 KB"


def test_stats_embed_unlimited_memory():
    usage = make_usage(memory_limit_bytes=0)

    embed = build_stats_embed("srv001", usage)

    fields = {f.name: f.value for f in embed.fields}
    assert fields["Memory"] == "512.0 MB / Unlimited"


def test_stats_embed_unlimited_disk():
    usage = make_usage(disk_limit_bytes=0)

    embed = build_stats_embed("srv001", usage)

    fields = {f.name: f.value for f in embed.fields}
    assert fields["Disk"] == "2.0 GB / Unlimited"


def test_stats_embed_offline_skips_resource_fields():
    usage = make_usage(
        current_state="offline",
        memory_bytes=0,
        cpu_absolute=0,
        disk_bytes=0,
        network_rx_bytes=0,
        network_tx_bytes=0,
        uptime=0,
    )

    embed = build_stats_embed("srv001", usage)

    field_names = [f.name for f in embed.fields]
    assert field_names == ["State", "Uptime"]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["State"] == "Offline"
    assert fields["Uptime"] == "0"


# --- /server stats command --------------------------------------------------------------


async def test_server_stats_replies_with_embed_on_success():
    cog = make_cog()
    cog.client.get_resource_usage.return_value = make_usage()
    interaction = make_interaction()

    await PowerCog.server_stats.callback(cog, interaction, "srv001")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    _, kwargs = interaction.edit_original_response.call_args
    assert isinstance(kwargs["embed"], discord.Embed)


async def test_server_stats_reports_server_not_found():
    cog = make_cog()
    cog.client.get_resource_usage.side_effect = PterodactylAPIError("srv001", 404, "Not found")
    interaction = make_interaction()

    await PowerCog.server_stats.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_once_with(
        content="No server found with identifier `srv001`."
    )


async def test_server_stats_reports_unreachable_api():
    cog = make_cog()
    cog.client.get_resource_usage.side_effect = httpx.ConnectError("connection refused")
    interaction = make_interaction()

    await PowerCog.server_stats.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_once_with(content=UNREACHABLE_MESSAGE)


async def test_server_stats_reports_generic_api_error():
    cog = make_cog()
    cog.client.get_resource_usage.side_effect = PterodactylAPIError("srv001", 500, "boom")
    interaction = make_interaction()

    await PowerCog.server_stats.callback(cog, interaction, "srv001")

    interaction.edit_original_response.assert_awaited_once_with(content=API_ERROR_MESSAGE)
