import discord
from discord import app_commands   # slash commands
from discord.ext import commands   # Cog

import database                    # our own file: database.py


class Analytics(commands.Cog):
    """Everything that READS data from the database and shows results."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="top", description="Most active members in the last 7 days")
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction):
        # Ask the database for the top 5 chatters of THIS server in the last 7 days.
        rows = await database.top_chatters(
            self.bot.pool, interaction.guild_id, 7, 5
        )

        # If nothing is saved yet, say so instead of sending an empty message.
        if not rows:
            await interaction.response.send_message("No messages saved yet.")
            return

        # Build one text line per person, like: "1. Hussein: 42 messages".
        lines = [
            f"{position}. {row['author_name']}: {row['total']} messages"
            for position, row in enumerate(rows, start=1)
        ]
        await interaction.response.send_message("\n".join(lines))


async def setup(bot):
    """discord.py calls this when the cog file is loaded."""
    await bot.add_cog(Analytics(bot))