import os                          # to read environment variables (from .env)
import discord                     # the Discord library
from discord import app_commands   # needed for slash commands (/)
from dotenv import load_dotenv     # loads the .env file

import database                    # our own file: database.py

# Read the .env file so its values become available through os.environ.
load_dotenv()

# Intents = permissions we ask Discord for.
intents = discord.Intents.default()

# Without this, message.content comes back empty.
# You must ALSO enable "Message Content Intent" in the Developer Portal.
intents.message_content = True


class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)

        # The "tree" is where our slash commands get stored.
        self.tree = app_commands.CommandTree(self)

        # The database connection pool. It's None until setup_hook fills it.
        self.pool = None

    async def setup_hook(self):
        """Runs once, before the bot starts receiving events."""

        # 1) Connect to the database and make sure the table exists.
        self.pool = await database.create_pool(os.environ["DATABASE_URL"])
        await database.init_schema(self.pool)
        print("Database is ready")

        # 2) Sync (send) our slash commands to Discord.
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            # Only for this server, appears instantly (good while developing).
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            # For all servers, can take a while to show up.
            await self.tree.sync()

    async def close(self):
        """Runs when the bot shuts down: close the database cleanly."""
        if self.pool:
            await self.pool.close()
        await super().close()


bot = MyBot()


# ---------------------------------------------------------
# Events
# ---------------------------------------------------------
@bot.event
async def on_ready():
    """Runs when the bot has successfully connected to Discord."""
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message):
    """Runs for every new message the bot can see."""

    # Ignore bots (including ourselves) and DMs.
    if message.author.bot or message.guild is None:
        return

    # try/except: if saving fails, print the error instead of crashing the bot.
    try:
        await database.save_message(bot.pool, message)
        print(f"Saved: {message.author.name}: {message.content}")
    except Exception as e:
        print(f"Failed to save message: {e}")


@bot.event
async def on_raw_message_edit(payload):
    """Runs when ANY message is edited, even old ones the bot never cached."""

    if payload.guild_id is None:
        return

    # Discord also fires this when only a link preview changes.
    # In that case there is no new text / edit time, so we skip it.
    new_content = payload.data.get("content")
    edited_ts = payload.data.get("edited_timestamp")
    if new_content is None or edited_ts is None:
        return

    try:
        await database.update_edit(
            bot.pool,
            payload.message_id,
            new_content,
            discord.utils.parse_time(edited_ts),
        )
        print(f"Edited: {payload.message_id}")
    except Exception as e:
        print(f"Failed to save edit: {e}")


@bot.event
async def on_raw_message_delete(payload):
    """Runs when ANY message is deleted, even old ones the bot never cached."""

    if payload.guild_id is None:
        return

    try:
        await database.mark_deleted(
            bot.pool, payload.message_id, discord.utils.utcnow()
        )
        print(f"Deleted: {payload.message_id}")
    except Exception as e:
        print(f"Failed to save delete: {e}")


# ---------------------------------------------------------
# Slash commands
# ---------------------------------------------------------
@bot.tree.command(name="ping", description="Check that the bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


# Start the bot (always the last line).
bot.run(os.environ["DISCORD_TOKEN"])