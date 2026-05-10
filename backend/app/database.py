from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import sqlalchemy as sa

    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        has_alembic_version = inspector.has_table("alembic_version")
        has_app_tables = inspector.has_table("tracks")

    if has_app_tables and not has_alembic_version:
        # DB was created by pre-Alembic create_all(); stamp it so migrations don't re-run
        command.stamp(alembic_cfg, "head")
    else:
        command.upgrade(alembic_cfg, "head")
