import asyncpg  # library that talks to PostgreSQL


async def create_pool(database_url):
    """Open a pool of database connections and return it."""
    return await asyncpg.create_pool(database_url)

async def init_schema(pool):
    """Create the table (and add newer columns) if they don't exist yet."""

    # CREATE TABLE IF NOT EXISTS: do nothing if the table is already there.
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id  BIGINT PRIMARY KEY,
            guild_id    BIGINT NOT NULL,
            channel_id  BIGINT NOT NULL,
            author_id   BIGINT NOT NULL,
            author_name TEXT   NOT NULL,
            content     TEXT   NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL
        )
    """)

    # CREATE TABLE does not change a table that already exists,
    # so newer columns are added with ALTER TABLE.
    # IF NOT EXISTS makes it safe to run on every startup.
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ"
    )
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
    )

    # One row per (message, user, emoji): "this user reacted with this emoji
    # on this message".
    #
    # PRIMARY KEY on all three columns together means the same person can't
    # be saved twice with the same emoji on the same message.
    #
    # emoji is TEXT because it can be a normal emoji ("😂") or a custom
    # server emoji (looks like "<:name:123456>").
    #
    # We do NOT link this table to the messages table on purpose: a reaction
    # can arrive for an old message that we never saved, and we still want it.
    #
    # created_at is when WE saw the reaction (DEFAULT NOW() fills it in).
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            message_id BIGINT NOT NULL,
            guild_id   BIGINT NOT NULL,
            user_id    BIGINT NOT NULL,
            emoji      TEXT   NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (message_id, user_id, emoji)
        )
    """)

    # reply_to_id: the ID of the message this one is a reply to.
    # It stays empty (NULL) if the message is not a reply.
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_id BIGINT"
    )

    # has_attachment: TRUE if the message has an uploaded file or image.
    # Notice there is NO default value on purpose. For the old messages we
    # saved before this column existed, we don't know the answer, so they
    # stay NULL ("unknown") instead of a wrong FALSE ("no attachment").
    await pool.execute(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS has_attachment BOOLEAN"
    )

async def save_message(pool, message):
    """Insert one Discord message as a new row.

    Returns True if a new row was saved, False if it was already saved before.
    """

    # If this message is a reply, message.reference points to the original
    # message. Otherwise message.reference is None.
    # The extra "message.reference is not None" check avoids an error
    # for normal messages.
    reply_to_id = None
    if message.reference is not None:
        reply_to_id = message.reference.message_id

    # message.attachments is a list of uploaded files. An empty list means
    # no files, so bool([]) is False and bool([file]) is True.
    # (Links and GIFs from sites are "embeds", not attachments, so they
    # don't count here.)
    has_attachment = bool(message.attachments)

    status = await pool.execute(
        """
        INSERT INTO messages
            (message_id, guild_id, channel_id, author_id,
             author_name, content, created_at, edited_at,
             reply_to_id, has_attachment)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (message_id) DO NOTHING
        """,
        message.id,
        message.guild.id,
        message.channel.id,
        message.author.id,
        message.author.name,
        message.content,
        message.created_at,
        message.edited_at,
        reply_to_id,
        has_attachment,
    )
    return status.endswith(" 1")

async def update_edit(pool, message_id, new_content, edited_at):
    """Overwrite the text of a message and remember when it was edited."""
    await pool.execute(
        "UPDATE messages SET content = $1, edited_at = $2 WHERE message_id = $3",
        new_content,
        edited_at,
        message_id,
    )


async def mark_deleted(pool, message_id, deleted_at):
    """Mark a message as deleted. We keep the row, we only set deleted_at."""
    await pool.execute(
        "UPDATE messages SET deleted_at = $1 WHERE message_id = $2",
        deleted_at,
        message_id,
    )

async def add_reaction(pool, guild_id, message_id, user_id, emoji):
    """Save that a user added a reaction to a message."""

    # ON CONFLICT DO NOTHING: if this exact reaction is already saved, skip it.
    await pool.execute(
        """
        INSERT INTO reactions (message_id, guild_id, user_id, emoji)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        """,
        message_id,
        guild_id,
        user_id,
        emoji,
    )


async def remove_reaction(pool, message_id, user_id, emoji):
    """Forget a reaction, because the user removed it from the message."""

    # Here we really DELETE the row: if the user took the reaction back,
    # it no longer counts.
    await pool.execute(
        "DELETE FROM reactions WHERE message_id = $1 AND user_id = $2 AND emoji = $3",
        message_id,
        user_id,
        emoji,
    )

async def get_message_texts(pool, guild_id, days):
    """Return the text of every saved message of a server in the last N days."""

    # We only need the text, so we select just the content column.
    # deleted_at IS NULL -> skip messages that were deleted.
    rows = await pool.fetch(
        """
        SELECT content
        FROM messages
        WHERE guild_id = $1
          AND deleted_at IS NULL
          AND created_at > NOW() - make_interval(days => $2)
        """,
        guild_id,
        days,
    )

    # fetch() returns row objects. We turn them into a plain list of strings.
    return [row["content"] for row in rows]

async def top_chatters(pool, guild_id, days, limit):
    """Return the most active members of a server in the last N days."""

    # COUNT(*) counts the rows (= number of messages).
    # GROUP BY author_id makes ONE row per person instead of one per message.
    # MAX(author_name) picks one name per person (names can change over time).
    # ORDER BY total DESC puts the biggest count first.
    # LIMIT $3 returns only the first N rows.
    # deleted_at IS NULL skips messages that were deleted.
    return await pool.fetch(
        """
        SELECT MAX(author_name) AS author_name, COUNT(*) AS total
        FROM messages
        WHERE guild_id = $1
          AND deleted_at IS NULL
          AND created_at > NOW() - make_interval(days => $2)
        GROUP BY author_id
        ORDER BY total DESC
        LIMIT $3
        """,
        guild_id,
        days,
        limit,
    )


