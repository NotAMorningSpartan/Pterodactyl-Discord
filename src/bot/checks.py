import logging

import discord
from discord import app_commands

logger = logging.getLogger("bot")

DENIAL_MESSAGE = "You don't have permission to use this command."


async def has_allowed_role(interaction: discord.Interaction) -> bool:
    """Predicate backing require_allowed_role(); also directly unit-testable."""
    allowed_role_id = interaction.client.settings.allowed_role_id
    member = interaction.user

    if isinstance(member, discord.Member) and any(role.id == allowed_role_id for role in member.roles):
        return True

    logger.info(
        "Denied '%s' invocation by %s (missing required role)",
        interaction.command.qualified_name if interaction.command else "unknown",
        interaction.user,
    )
    await interaction.response.send_message(DENIAL_MESSAGE, ephemeral=True)
    return False


def require_allowed_role():
    return app_commands.check(has_allowed_role)
