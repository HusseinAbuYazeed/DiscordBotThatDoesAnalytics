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
# Every emoji in this list counts as "laughing".
# Easy to edit: just add or remove emojis. 
# because people also use them for shock or sadness.)
LAUGH_EMOJIS = ["😂", "🤣", "😆", "😹","💀","😭"]

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

def format_hour(hour):
    """Turn 0-23 into a friendly text, like 21 -> '9 PM'."""

    # hour % 12 gives 0-11, and "or 12" turns the 0 into 12 (so 0 -> 12 AM).
    suffix = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12} {suffix}"

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

    @app_commands.command(name="me", description="Your personal stats in this server")
    @app_commands.guild_only()
    @app_commands.describe(days="How many days back to look (default 30)")
    async def me(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 30,
    ):
        # Give ourselves more than Discord's 3 seconds to reply.
        await interaction.response.defer(thinking=True)

        guild_id = interaction.guild_id
        user_id = interaction.user.id

        # Ask the database for the numbers.
        stats = await database.user_stats(self.bot.pool, guild_id, user_id, days)

        # If this user has no messages in the period, say so and stop.
        if stats["total"] == 0:
            await interaction.followup.send(
                f"No messages from you in the last {days} days."
            )
            return

        # Count this user's emojis, and keep the 3 most used.
        texts = await database.get_user_texts(self.bot.pool, guild_id, user_id, days)
        top_emojis = count_emojis(texts).most_common(3)

        # Build the emoji text, like "😂 x12 · 💔 x8". Or "None" if there are none.
        if top_emojis:
            emoji_text = " · ".join(f"{symbol} x{count}" for symbol, count in top_emojis)
        else:
            emoji_text = "None"

        # An embed is the nice-looking card Discord shows for bots.
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s stats",
            description=f"Last {days} days",
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Messages", value=str(stats["total"]))
        embed.add_field(name="Average length", value=f"{stats['avg_length']:.0f} chars")
        embed.add_field(name="Longest message", value=f"{stats['longest']} chars")
        embed.add_field(
            name="Most active around",
            value=f"{format_hour(stats['busiest_hour'])} (Cairo time)",
        )
        embed.add_field(name="Top emojis", value=emoji_text)

        await interaction.followup.send(embed=embed)
        
    @app_commands.command(name="jokes", description="Messages that made people laugh the most")
    @app_commands.guild_only()
    @app_commands.describe(
        days="How many days back to look (default 7)",
        min_laughs="Minimum number of people who laughed (default 2)",
    )
    async def jokes(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 7,
        min_laughs: app_commands.Range[int, 1, 20] = 2,
    ):
        await interaction.response.defer(thinking=True)

        rows = await database.top_jokes(
            self.bot.pool, interaction.guild_id, days, LAUGH_EMOJIS, min_laughs, 5
        )

        if not rows:
            await interaction.followup.send(
                f"No messages with at least {min_laughs} laughs in the last {days} days."
            )
            return

        lines = []
        for position, row in enumerate(rows, start=1):

            # Messages with only an image/GIF have no text. Show a label instead.
            text = row["content"]
            if not text:
                text = "(image or file)" if row["has_attachment"] else "(no text)"

            # Long messages would flood the card, so we cut them at 100 characters.
            if len(text) > 100:
                text = text[:100] + "..."

            # escape_markdown stops symbols like * or _ from breaking the formatting.
            text = discord.utils.escape_markdown(text)

            # Every message has a link that jumps straight to it.
            # A joke often needs the messages before it to make sense.
            link = (
                f"https://discord.com/channels/"
                f"{row['guild_id']}/{row['channel_id']}/{row['message_id']}"
            )

            lines.append(
                f"**{position}.** 😂 x{row['laughs']} - {row['author_name']}: "
                f"{text} [jump]({link})"
            )

        embed = discord.Embed(
            title=f"Most laughed-at messages (last {days} days)",
            description="\n".join(lines),
        )
        await interaction.followup.send(embed=embed)    
async def setup(bot):
    """discord.py calls this when the cog file is loaded."""
    await bot.add_cog(Analytics(bot))