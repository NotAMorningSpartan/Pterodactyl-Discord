from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot.checks import DENIAL_MESSAGE, has_allowed_role

ALLOWED_ROLE_ID = 555111


def make_interaction(*, member_role_ids: list[int] | None) -> AsyncMock:
    """member_role_ids=None simulates a non-guild-member invoker (e.g. a DM)."""
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.client = SimpleNamespace(settings=SimpleNamespace(allowed_role_id=ALLOWED_ROLE_ID))
    interaction.response = AsyncMock()
    interaction.command = SimpleNamespace(qualified_name="power start")

    if member_role_ids is None:
        interaction.user = AsyncMock(spec=discord.User)
    else:
        member = AsyncMock(spec=discord.Member)
        member.roles = [SimpleNamespace(id=role_id) for role_id in member_role_ids]
        interaction.user = member

    return interaction


async def test_has_allowed_role_allows_member_with_role():
    interaction = make_interaction(member_role_ids=[111, ALLOWED_ROLE_ID, 222])

    result = await has_allowed_role(interaction)

    assert result is True
    interaction.response.send_message.assert_not_called()


async def test_has_allowed_role_denies_member_without_role():
    interaction = make_interaction(member_role_ids=[111, 222])

    result = await has_allowed_role(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once_with(DENIAL_MESSAGE, ephemeral=True)


async def test_has_allowed_role_denies_non_member_user():
    interaction = make_interaction(member_role_ids=None)

    result = await has_allowed_role(interaction)

    assert result is False
    interaction.response.send_message.assert_awaited_once_with(DENIAL_MESSAGE, ephemeral=True)


def test_denial_message_reveals_no_server_or_role_details():
    assert "server" not in DENIAL_MESSAGE.lower()
    assert str(ALLOWED_ROLE_ID) not in DENIAL_MESSAGE
