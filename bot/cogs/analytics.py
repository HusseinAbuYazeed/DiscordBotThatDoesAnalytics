import discord
from discord import app_commands   # slash commands
from discord.ext import commands   # Cog
import re                          # regular expressions: find patterns in text
from collections import Counter    # a dictionary that counts things for us
import emoji                       # finds normal emojis inside text
import database                    # our own file: database.py

# A custom server emoji looks like "<:name:123456>" in the message text
# (or "<a:name:123456>" if it is animated).
# Pattern meaning:  <  a?  :  word  :  digits  >
#   a?  -> an optional "a"   \w+ -> the name   \d+ -> the number
CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")

def count_emojis(texts):
    """Count how many times each emoji appears in a list of messages."""

    # Counter works like a dictionary: counter["😂"] += 1
    counter = Counter()

    for text in texts:
        # 1) Custom emojis: findall returns every match, e.g. ["<:nour4:123>"].
        counter.update(CUSTOM_EMOJI.findall(text))

        # 2) Normal emojis: emoji_list returns a list of dictionaries
        # like {"emoji": "😂", "match_start": 0, "match_end": 1}.
        for item in emoji.emoji_list(text):
            counter[item["emoji"]] += 1

    return counter

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

    @app_commands.command(name="emojis", description="Most used emojis in messages")
    @app_commands.guild_only()
    @app_commands.describe(days="How many days back to look (default 30)")
    async def emojis(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 30,
    ):
        # defer() tells Discord "I'm working on it", so we can't run out
        # of the 3 seconds Discord gives us to reply.
        await interaction.response.defer(thinking=True)

        # Get the text of all messages from the database.
        texts = await database.get_message_texts(
            self.bot.pool, interaction.guild_id, days
        )

        # Count the emojis, then take the 10 most common ones.
        # most_common(10) returns a list like [("😂", 120), ("💔", 80), ...]
        top = count_emojis(texts).most_common(10)

        if not top:
            await interaction.followup.send("No emojis found in that period.")
            return

        # Build one line per emoji, like: "1. 😂 : 120 times".
        lines = [
            f"{position}. {symbol} : {count} times"
            for position, (symbol, count) in enumerate(top, start=1)
        ]

        header = f"Most used emojis in the last {days} days ({len(texts)} messages):"
        await interaction.followup.send(header + "\n" + "\n".join(lines))

async def setup(bot):
    """discord.py calls this when the cog file is loaded."""
    await bot.add_cog(Analytics(bot))