from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401  (importing registers the tables)
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def make_alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_there_is_exactly_one_migration_head() -> None:
    config = make_alembic_config("sqlite+aiosqlite:///unused.db")
    assert ScriptDirectory.from_config(config).get_heads() == ["0002"]


def test_upgrade_creates_the_same_tables_columns_and_indexes_as_the_models(
    tmp_path: Path,
) -> None:
    database_file = tmp_path / "migrated.db"
    command.upgrade(make_alembic_config(f"sqlite+aiosqlite:///{database_file}"), "head")

    engine = create_engine(f"sqlite:///{database_file}")
    try:
        inspector = inspect(engine)
        migrated_tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert migrated_tables == set(Base.metadata.tables)

        for table_name, table in Base.metadata.tables.items():
            migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
            assert migrated_columns == {column.name for column in table.columns}

            migrated_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            assert migrated_indexes == {index.name for index in table.indexes}
    finally:
        engine.dispose()


def test_downgrade_removes_every_table(tmp_path: Path) -> None:
    database_file = tmp_path / "roundtrip.db"
    config = make_alembic_config(f"sqlite+aiosqlite:///{database_file}")
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{database_file}")
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()
    finally:
        engine.dispose()
        
