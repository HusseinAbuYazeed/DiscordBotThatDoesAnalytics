import os                          # to read environment variables (from .env)
import discord                     # the Discord library
from discord.ext import commands   # commands.Bot is a Client that can load cogs
from dotenv import load_dotenv     # loads the .env file

import database                    # our own file: database.py

# Read the .env file so its values become available through os.environ.
load_dotenv()

# Intents = permissions we ask Discord for.
intents = discord.Intents.default()

# Without this, message.content comes back empty.
# You must ALSO enable "Message Content Intent" in the Developer Portal.
intents.message_content = True

# The cogs (files inside the cogs/ folder) that the bot should load.
COGS = ["cogs.logger", "cogs.analytics"]


class MyBot(commands.Bot):
    def __init__(self):
        # commands.Bot requires a command_prefix for old-style "!" commands.
        # We only use slash commands, so we set it to "mention the bot",
        # which means it will basically never trigger.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        # The database connection pool. It's None until setup_hook fills it.
        # Cogs reach it with self.bot.pool.
        self.pool = None

        # NOTE: commands.Bot already creates self.tree for slash commands,
        # so we must NOT create our own CommandTree here.

    async def setup_hook(self):
        """Runs once, before the bot starts receiving events."""

        # 1) Connect to the database and make sure the tables exist.
        self.pool = await database.create_pool(os.environ["DATABASE_URL"])
        await database.init_schema(self.pool)
        print("Database is ready")

        # 2) Load every cog. This is what registers their events and commands.
        for cog in COGS:
            await self.load_extension(cog)
            print(f"Loaded {cog}")

        # 3) Sync (send) our slash commands to Discord.
        # This must come AFTER loading the cogs, because the commands live in them.
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            # Only for this server, appears instantly (good while developing).
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            # For all servers, can take a while to show up.
            await self.tree.sync()

    async def on_ready(self):
        """Runs when the bot has successfully connected to Discord."""
        print(f"Logged in as {self.user}")

    async def close(self):
        """Runs when the bot shuts down: close the database cleanly."""
        if self.pool:
            await self.pool.close()
        await super().close()


bot = MyBot()
bot.run(os.environ["DISCORD_TOKEN"])