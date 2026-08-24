from discord.ext import commands


class PowerCog(commands.Cog, name="Power"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PowerCog(bot))
