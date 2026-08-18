from sqlalchemy import inspect, text

from imgbot.db import Database


async def test_existing_administrator_table_gets_display_name_column() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE administrators (id INTEGER PRIMARY KEY, telegram_user_id BIGINT)")
        )
    await database.create_schema()
    async with database.engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("administrators")
            }
        )
    assert "display_name" in columns
    await database.dispose()


async def test_create_schema_adds_start_page_tables() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    async with database.engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
    assert {"start_pages", "start_page_buttons", "start_page_photo_caches"} <= table_names
    await database.dispose()


async def test_existing_submission_table_gets_reply_bot_columns() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE submissions (id INTEGER PRIMARY KEY)"))
    await database.create_schema()
    async with database.engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("submissions")
            }
        )
    assert {"reply_bot_telegram_id", "reply_bot_username"} <= columns
    await database.dispose()
