import os                          # to read environment variables (from .env)
import asyncpg                     # library that talks to PostgreSQL
import discord                     # the Discord library
from discord import app_commands   # needed for slash commands (/)
from dotenv import load_dotenv     # loads the .env file

# Read the .env file so its values (token, guild id, database url) become
# available through os.environ / os.getenv.
load_dotenv()

# ---------------------------------------------------------
# Intents = permissions we ask Discord for.
# ---------------------------------------------------------
intents = discord.Intents.default()

# Without this line, message.content comes back empty.
# You must ALSO enable "Message Content Intent" in the Developer Portal
# (Bot tab), otherwise it still won't work.
intents.message_content = True


# ---------------------------------------------------------
# Our bot class
# ---------------------------------------------------------
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)

        # The "tree" is where our slash commands get stored.
        self.tree = app_commands.CommandTree(self)

        # Placeholder for the database connection pool.
        # It's None for now; we fill it in setup_hook below.
        self.db = None

    async def setup_hook(self):
        """Runs once, before the bot starts receiving events."""

        # 1) Connect to the database.
        # A "pool" is a group of ready-made connections. It's better than
        # opening a brand new connection for every single message.
        self.db = await asyncpg.create_pool(os.environ["DATABASE_URL"])
        print("Connected to database")

        # 2) Sync (send) our slash commands to Discord.
        # Without a sync, the commands will not show up when you type "/".
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            # GUILD_ID exists: register commands for that server only.
            # They appear instantly, which is great while developing.
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            # No GUILD_ID: register commands globally (all servers).
            # Can take a while to show up the first time.
            await self.tree.sync()

    async def close(self):
        """Runs when the bot shuts down: close the database connection cleanly."""
        if self.db:
            await self.db.close()
        await super().close()


bot = MyBot()


# ---------------------------------------------------------
# Events = things that happen. We tell the bot what to do when they do.
# ---------------------------------------------------------
@bot.event
async def on_ready():
    """Runs when the bot has successfully connected to Discord."""
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message):
    """Runs for EVERY new message the bot can see. This is the core of the project."""

    # Ignore messages written by bots (including our own bot).
    if message.author.bot:
        return

    # Ignore direct messages (DMs). We only want messages inside servers.
    if message.guild is None:
        return

    # For now we just print the message info in the terminal.
    # Later, instead of printing, we will save these same values in the database.
    print("-" * 40)
    print("Server:  ", message.guild.name, f"({message.guild.id})")
    print("Channel: ", message.channel.name, f"({message.channel.id})")
    print("Author:  ", message.author.name, f"({message.author.id})")
    print("Time:    ", message.created_at)
    print("Content: ", message.content)


# ---------------------------------------------------------
# Slash command (just to test that the bot is alive)
# ---------------------------------------------------------
@bot.tree.command(name="ping", description="Check that the bot is alive")
async def ping(interaction: discord.Interaction):
    # "interaction" represents the user running the command.
    # We use it to reply to them.
    await interaction.response.send_message("pong")


# ---------------------------------------------------------
# Start the bot (always the last line)
# ---------------------------------------------------------
bot.run(os.environ["DISCORD_TOKEN"])