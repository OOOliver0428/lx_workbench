from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.config import get_settings
from app.database import create_database_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def _include_sqlite_object(
    obj: object,
    _name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: object | None,
) -> bool:
    """Ignore the one SQLite FK option that SQLAlchemy cannot reflect.

    ``leader_id`` was added with SQLite's inline ``REFERENCES`` syntax so the
    database enforces ``ON DELETE SET NULL``. SQLAlchemy's SQLite inspector
    only recovers delete options from table-level constraints, which otherwise
    makes every ``alembic check`` report a false remove/add pair.
    """

    if type_ != "foreign_key_constraint":
        return True
    table = getattr(obj, "table", None)
    elements = getattr(obj, "elements", ())
    column_names = tuple(
        getattr(getattr(element, "parent", None), "name", None)
        for element in elements
    )
    return not (
        getattr(table, "name", None) == "users"
        and column_names == ("leader_id",)
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_database_engine(settings)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=connection.dialect.name == "sqlite",
                include_object=(
                    _include_sqlite_object
                    if connection.dialect.name == "sqlite"
                    else None
                ),
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
