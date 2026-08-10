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
