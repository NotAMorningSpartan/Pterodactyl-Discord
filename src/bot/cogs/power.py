from __future__ import annotations

import logging
import time

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from bot.checks import require_allowed_role
from bot.pterodactyl.client import PterodactylAPIError, PterodactylClient
from bot.pterodactyl.models import PowerAction, ResourceUsage, Server

logger = logging.getLogger("bot")

SERVERS_PER_PAGE = 20
SERVER_CACHE_TTL_SECONDS = 60.0
UNREACHABLE_MESSAGE = "Couldn't reach the Pterodactyl panel. Please try again in a moment."
API_ERROR_MESSAGE = "The Pterodactyl panel returned an error. Please try again in a moment."

# States that make a given power action redundant, and the message to show instead of
# re-sending it. Restart has no natural "already there" state, so it's intentionally absent.
ALREADY_IN_STATE: dict[str, tuple[frozenset[str], str]] = {
    "start": (frozenset({"running", "starting"}), "already running"),
    "stop": (frozenset({"offline", "stopping"}), "already stopped"),
    "kill": (frozenset({"offline"}), "already stopped — nothing to kill"),
}


def build_server_embeds(servers: list[Server]) -> list[discord.Embed]:
    pages = [
        servers[i : i + SERVERS_PER_PAGE] for i in range(0, len(servers), SERVERS_PER_PAGE)
    ]
    total_pages = len(pages)

    embeds: list[discord.Embed] = []
    for page_number, page in enumerate(pages, start=1):
        embed = discord.Embed(title="Pterodactyl Servers")
        for server in page:
            embed.add_field(
                name=server.name[:256],
                value=f"**Identifier:** `{server.identifier}`\n**Node:** {server.node}",
                inline=False,
            )
        if total_pages > 1:
            embed.set_footer(text=f"Page {page_number}/{total_pages}")
        embeds.append(embed)

    return embeds


def _format_duration(milliseconds: int) -> str:
    total_seconds = milliseconds // 1000
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    unit = "B"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024:
            break
        value /= 1024

    return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"


def _format_usage_over_limit(used_bytes: int, limit_bytes: int) -> str:
    limit = "Unlimited" if limit_bytes == 0 else _format_bytes(limit_bytes)
    return f"{_format_bytes(used_bytes)} / {limit}"


def build_stats_embed(identifier: str, usage: ResourceUsage) -> discord.Embed:
    embed = discord.Embed(title=f"Server Stats: `{identifier}`")
    embed.add_field(name="State", value=usage.current_state.capitalize(), inline=True)

    if usage.current_state == "offline":
        embed.add_field(name="Uptime", value="0", inline=True)
        return embed

    embed.add_field(name="Uptime", value=_format_duration(usage.uptime), inline=True)
    embed.add_field(
        name="Memory",
        value=_format_usage_over_limit(usage.memory_bytes, usage.memory_limit_bytes),
        inline=True,
    )
    embed.add_field(name="CPU", value=f"{usage.cpu_absolute:.1f}%", inline=True)
    embed.add_field(
        name="Disk",
        value=_format_usage_over_limit(usage.disk_bytes, usage.disk_limit_bytes),
        inline=True,
    )
    embed.add_field(
        name="Network I/O",
        value=f"↓ {_format_bytes(usage.network_rx_bytes)} / ↑ {_format_bytes(usage.network_tx_bytes)}",
        inline=True,
    )
    return embed


class ServerListPaginator(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], *, author_id: int) -> None:
        super().__init__(timeout=180)
        self.embeds = embeds
        self.author_id = author_id
        self.index = 0
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.previous_button.disabled = self.index == 0
        self.next_button.disabled = self.index == len(self.embeds) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


class KillConfirmView(discord.ui.View):
    def __init__(self, *, author_id: int) -> None:
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="Force Kill", style=discord.ButtonStyle.danger)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        self._disable_all()
        await interaction.response.edit_message(content="Force-killing server...", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._disable_all()
        await interaction.response.edit_message(content="Cancelled.", view=self)
        self.stop()

    async def on_timeout(self) -> None:
        self.confirmed = False


class PowerCog(commands.Cog, name="Power"):
    server_group = app_commands.Group(
        name="server", description="Control a Pterodactyl server's power state."
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.client = PterodactylClient(bot.settings)  # type: ignore[attr-defined]
        self._server_cache: list[Server] = []
        self._server_cache_expiry = 0.0

    async def cog_unload(self) -> None:
        await self.client.aclose()

    async def _get_cached_servers(self) -> list[Server]:
        if time.monotonic() >= self._server_cache_expiry:
            self._server_cache = await self.client.list_servers()
            self._server_cache_expiry = time.monotonic() + SERVER_CACHE_TTL_SECONDS
        return self._server_cache

    async def _autocomplete_server(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            servers = await self._get_cached_servers()
        except (httpx.RequestError, PterodactylAPIError):
            return []

        current_lower = current.lower()
        matches = [
            server
            for server in servers
            if current_lower in server.name.lower() or current_lower in server.identifier.lower()
        ][:25]

        return [
            app_commands.Choice(name=f"{server.name} ({server.identifier})"[:100], value=server.identifier)
            for server in matches
        ]

    @staticmethod
    def _describe_error(identifier: str, error: httpx.RequestError | PterodactylAPIError) -> str:
        if isinstance(error, PterodactylAPIError):
            if error.status_code == 404:
                return f"No server found with identifier `{identifier}`."
            return API_ERROR_MESSAGE
        return UNREACHABLE_MESSAGE

    async def _execute_power_action(
        self, interaction: discord.Interaction, identifier: str, action: PowerAction
    ) -> None:
        already = ALREADY_IN_STATE.get(action)
        try:
            if already is not None:
                states, description = already
                current_state = await self.client.get_power_state(identifier)
                if current_state in states:
                    await interaction.edit_original_response(
                        content=f"`{identifier}` is {description}."
                    )
                    return
            await self.client.send_power_action(identifier, action)
        except (httpx.RequestError, PterodactylAPIError) as error:
            logger.error(
                "Failed to send power action '%s' to '%s'", action, identifier, exc_info=True
            )
            await interaction.edit_original_response(content=self._describe_error(identifier, error))
            return

        logger.info("Sent power action '%s' to '%s' (requested by %s)", action, identifier, interaction.user)
        await interaction.edit_original_response(content=f"Sent **{action}** to `{identifier}`.")

    async def _show_stats(self, interaction: discord.Interaction, identifier: str) -> None:
        try:
            usage = await self.client.get_resource_usage(identifier)
        except (httpx.RequestError, PterodactylAPIError) as error:
            logger.error("Failed to get resource usage for '%s'", identifier, exc_info=True)
            await interaction.edit_original_response(content=self._describe_error(identifier, error))
            return

        await interaction.edit_original_response(embed=build_stats_embed(identifier, usage))

    @app_commands.command(name="servers", description="List all Pterodactyl servers.")
    @require_allowed_role()
    async def servers(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            servers = await self.client.list_servers()
        except httpx.RequestError:
            logger.error("Pterodactyl API unreachable while listing servers", exc_info=True)
            await interaction.edit_original_response(content=UNREACHABLE_MESSAGE)
            return
        except PterodactylAPIError:
            logger.error("Pterodactyl API error while listing servers", exc_info=True)
            await interaction.edit_original_response(content=API_ERROR_MESSAGE)
            return

        if not servers:
            await interaction.edit_original_response(content="No servers found.")
            return

        embeds = build_server_embeds(servers)

        if len(embeds) == 1:
            await interaction.edit_original_response(embed=embeds[0])
            return

        view = ServerListPaginator(embeds, author_id=interaction.user.id)
        view.message = await interaction.edit_original_response(embed=embeds[0], view=view)

    @server_group.command(name="stats", description="Show a server's current resource usage.")
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_allowed_role()
    async def server_stats(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._show_stats(interaction, server)

    @server_group.command(name="start", description="Start a server.")
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_allowed_role()
    async def server_start(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._execute_power_action(interaction, server, "start")

    @server_group.command(name="restart", description="Restart a server.")
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_allowed_role()
    async def server_restart(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._execute_power_action(interaction, server, "restart")

    @server_group.command(name="stop", description="Gracefully stop a server.")
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_allowed_role()
    async def server_stop(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._execute_power_action(interaction, server, "stop")

    @server_group.command(
        name="kill", description="Force-kill a server (terminates the process; requires confirmation)."
    )
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_allowed_role()
    async def server_kill(self, interaction: discord.Interaction, server: str) -> None:
        await interaction.response.defer(ephemeral=True)

        view = KillConfirmView(author_id=interaction.user.id)
        await interaction.edit_original_response(
            content=(
                f"This will **force-kill** `{server}`, immediately terminating the process.\n"
                "In-progress writes may be lost, and this cannot be undone. Are you sure?"
            ),
            view=view,
        )

        await view.wait()
        if not view.confirmed:
            return

        await self._execute_power_action(interaction, server, "kill")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PowerCog(bot))
