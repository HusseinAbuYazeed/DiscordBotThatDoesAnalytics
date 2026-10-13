from datetime import timedelta     # to say "30 days ago"

import discord
from discord import app_commands   # slash commands
from discord.ext import commands   # Cog

import database                    # our own file: database.py


def should_save(message):
    """The ONE place that decides if a message is worth saving.

    Both live logging (on_message) and /backfill use this, so the rule
    can never be different between them.
    """

    # Ignore messages written by bots (including our own bot).
    if message.author.bot:
        return False

    # Ignore direct messages (DMs). We only want messages inside servers.
    if message.guild is None:
        return False

    # Ignore system messages (like "X joined the server" or "pinned a message").
    # Only real messages and replies are interesting.
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return False

    return True


class Logger(commands.Cog):
    """Everything that SAVES data into the database."""

    def __init__(self, bot):
        # Keep the bot so we can reach the database with self.bot.pool.
        self.bot = bot

    # -----------------------------------------------------
    # Live events
    # -----------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        """Runs for every new message the bot can see."""

        if not should_save(message):
            return

        # try/except: if saving fails, print the error instead of crashing the bot.
        try:
            await database.save_message(self.bot.pool, message)
            print(f"Saved: {message.author.name}: {message.content}")
        except Exception as e:
            print(f"Failed to save message: {e}")

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
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
                self.bot.pool,
                payload.message_id,
                new_content,
                discord.utils.parse_time(edited_ts),
            )
            print(f"Edited: {payload.message_id}")
        except Exception as e:
            print(f"Failed to save edit: {e}")

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        """Runs when ANY message is deleted, even old ones the bot never cached."""

        if payload.guild_id is None:
            return

        try:
            await database.mark_deleted(
                self.bot.pool, payload.message_id, discord.utils.utcnow()
            )
            print(f"Deleted: {payload.message_id}")
        except Exception as e:
            print(f"Failed to save delete: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Runs when ANY user adds a reaction to ANY message (even old ones)."""

        if payload.guild_id is None:
            return

        # payload.member is the person who reacted. Ignore bots.
        if payload.member is not None and payload.member.bot:
            return

        try:
            # str(payload.emoji) gives "😂" for a normal emoji,
            # or "<:name:123456>" for a custom server emoji.
            await database.add_reaction(
                self.bot.pool,
                payload.guild_id,
                payload.message_id,
                payload.user_id,
                str(payload.emoji),
            )
            print(f"Reaction added: {payload.emoji} on {payload.message_id}")
        except Exception as e:
            print(f"Failed to save reaction: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Runs when a user removes their reaction from a message."""

        if payload.guild_id is None:
            return

        try:
            # If this reaction was never saved, DELETE matches nothing. That's fine.
            await database.remove_reaction(
                self.bot.pool,
                payload.message_id,
                payload.user_id,
                str(payload.emoji),
            )
            print(f"Reaction removed: {payload.emoji} on {payload.message_id}")
        except Exception as e:
            print(f"Failed to remove reaction: {e}")

    # -----------------------------------------------------
    # Backfill command
    # -----------------------------------------------------
    @app_commands.command(name="backfill", description="Load old messages into the database")
    @app_commands.guild_only()  # this command only makes sense inside a server
    @app_commands.describe(days="How many days back to load (default 30)")
    async def backfill(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 365] = 30,
    ):
        # Only server admins can run this heavy command.
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Only admins can use this command.", ephemeral=True
            )
            return

        # Loading history can take minutes, but Discord wants an answer within
        # 3 seconds. defer() says "I'm working on it" and gives us more time.
        await interaction.response.defer(thinking=True)

        # Only messages newer than this moment will be loaded.
        cutoff = discord.utils.utcnow() - timedelta(days=days)

        saved = 0     # messages that were new and got saved
        skipped = 0   # messages that were already in the database
        guild = interaction.guild

        # Go through every normal text channel in the server.
        # (Threads and forum channels are not included in this version.)
        for channel in guild.text_channels:

            # Skip channels the bot isn't allowed to read.
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.read_message_history):
                print(f"Backfill: skipping #{channel.name} (no permission)")
                continue

            channel_count = 0

            # channel.history() fetches old messages from Discord, 100 at a time.
            # discord.py waits by itself when Discord says "slow down".
            async for message in channel.history(limit=None, after=cutoff, oldest_first=True):

                # Same rule as live logging.
                if not should_save(message):
                    continue

                try:
                    if await database.save_message(self.bot.pool, message):
                        saved += 1
                    else:
                        skipped += 1
                    channel_count += 1
                except Exception as e:
                    print(f"Backfill: failed to save {message.id}: {e}")

            print(f"Backfill: #{channel.name} done ({channel_count} messages)")

        await interaction.followup.send(
            f"Done. Saved {saved} new messages, skipped {skipped} that were already saved."
        )

async def setup(bot):
    """discord.py calls this when the cog file is loaded."""
    await bot.add_cog(Logger(bot))