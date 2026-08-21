from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from imgbot.models import Base


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            missing_columns = await connection.run_sync(self._missing_compatibility_columns)
            if "administrators.display_name" in missing_columns:
                await connection.execute(
                    text("ALTER TABLE administrators ADD COLUMN display_name VARCHAR(255)")
                )
            if "submissions.reply_bot_telegram_id" in missing_columns:
                await connection.execute(
                    text("ALTER TABLE submissions ADD COLUMN reply_bot_telegram_id BIGINT")
                )
            if "submissions.reply_bot_username" in missing_columns:
                await connection.execute(
                    text("ALTER TABLE submissions ADD COLUMN reply_bot_username VARCHAR(64)")
                )
            if "submissions.sending_started_at" in missing_columns:
                timestamp_type = (
                    "TIMESTAMP WITH TIME ZONE"
                    if connection.dialect.name == "postgresql"
                    else "DATETIME"
                )
                await connection.execute(
                    text(
                        "ALTER TABLE submissions "
                        f"ADD COLUMN sending_started_at {timestamp_type}"
                    )
                )
            if "submissions.reply_error_type" in missing_columns:
                await connection.execute(
                    text("ALTER TABLE submissions ADD COLUMN reply_error_type VARCHAR(64)")
                )
            submission_columns = await connection.run_sync(
                lambda sync_connection: (
                    {
                        column["name"]
                        for column in inspect(sync_connection).get_columns("submissions")
                    }
                    if "submissions"
                    in set(inspect(sync_connection).get_table_names())
                    else set()
                )
            )
            queue_index_columns = {
                "bot_instance_id",
                "reply_status",
                "next_retry_at",
                "reply_not_before",
                "sent_at",
            }
            if queue_index_columns <= submission_columns:
                await connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_submissions_reply_queue "
                        "ON submissions "
                        "(bot_instance_id, reply_status, next_retry_at, "
                        "reply_not_before, sent_at)"
                    )
                )

    @staticmethod
    def _missing_compatibility_columns(connection: Connection) -> set[str]:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        missing: set[str] = set()
        if "administrators" in table_names:
            columns = {
                column["name"] for column in inspector.get_columns("administrators")
            }
            if "display_name" not in columns:
                missing.add("administrators.display_name")
        if "submissions" in table_names:
            columns = {column["name"] for column in inspector.get_columns("submissions")}
            if "reply_bot_telegram_id" not in columns:
                missing.add("submissions.reply_bot_telegram_id")
            if "reply_bot_username" not in columns:
                missing.add("submissions.reply_bot_username")
            if "sending_started_at" not in columns:
                missing.add("submissions.sending_started_at")
            if "reply_error_type" not in columns:
                missing.add("submissions.reply_error_type")
        return missing

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session
