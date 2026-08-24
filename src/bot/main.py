import argparse
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Settings

logger = logging.getLogger("bot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bot.main",
        description="Discord bot for controlling Pterodactyl panel server power states.",
    )
    return parser.parse_args()


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # httpx/httpcore log full request/response headers -- including our
    # Authorization: Bearer <api-key> headers -- at DEBUG. Cap them below
    # DEBUG regardless of LOG_LEVEL so API keys never reach a log record.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, root.level))
    logging.getLogger("httpcore").setLevel(max(logging.WARNING, root.level))


class PowerCommandTree(app_commands.CommandTree):
    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = error.__cause__ or error
        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        logger.error(
            "Command '%s' invoked by %s raised %s: %s",
            command_name,
            interaction.user,
            type(original).__name__,
            original,
        )


class PterodactylBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            tree_cls=PowerCommandTree,
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        await self.load_extension("bot.cogs.power")

        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(
            "Synced %d slash command(s) to guild %s", len(synced), self.settings.discord_guild_id
        )

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else None)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        logger.info(
            "Command '%s' invoked by %s (id=%s) in guild %s",
            command.qualified_name,
            interaction.user,
            interaction.user.id,
            interaction.guild_id,
        )


def main() -> None:
    parse_args()
    settings = Settings()
    configure_logging(settings.log_level)

    logger.info("Starting bot")
    bot = PterodactylBot(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
