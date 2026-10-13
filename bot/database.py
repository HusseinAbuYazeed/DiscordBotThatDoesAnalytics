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


async def save_message(pool, message):
    """Insert one Discord message as a new row."""

    # $1, $2, ... are placeholders filled with the values after the SQL text.
    # ON CONFLICT DO NOTHING: skip silently if this message is already saved.
    await pool.execute(
        """
        INSERT INTO messages
            (message_id, guild_id, channel_id, author_id,
             author_name, content, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (message_id) DO NOTHING
        """,
        message.id,
        message.guild.id,
        message.channel.id,
        message.author.id,
        message.author.name,
        message.content,
        message.created_at,
    )


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