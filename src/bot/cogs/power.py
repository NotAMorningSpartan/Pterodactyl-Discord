from __future__ import annotations

import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from bot.checks import require_allowed_role
from bot.pterodactyl.client import PterodactylAPIError, PterodactylClient
from bot.pterodactyl.models import Server

logger = logging.getLogger("bot")

SERVERS_PER_PAGE = 20
UNREACHABLE_MESSAGE = "Couldn't reach the Pterodactyl panel. Please try again in a moment."
API_ERROR_MESSAGE = "The Pterodactyl panel returned an error. Please try again in a moment."


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


class PowerCog(commands.Cog, name="Power"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.client = PterodactylClient(bot.settings)  # type: ignore[attr-defined]

    async def cog_unload(self) -> None:
        await self.client.aclose()

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PowerCog(bot))
