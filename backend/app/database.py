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
    import logging
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import sqlalchemy as sa

    logger = logging.getLogger(__name__)
    alembic_cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Tables that the initial migration (d8524591de41) creates
    _initial_schema_tables = {
        "app_settings", "tracks", "url_sources", "youtube_oauth_tokens",
        "youtube_playlist_syncs", "download_jobs", "playlist_sync_tracks", "playlist_tracks",
    }

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        existing_tables = set(inspector.get_table_names())

    has_alembic_version = "alembic_version" in existing_tables
    partial_tables = existing_tables & _initial_schema_tables

    # alembic_version table may exist but be empty when a previous migration run
    # crashed after CREATE TABLE but before committing the version row.  In that
    # case Alembic would attempt to re-run all migrations and fail with
    # "table already exists", causing an infinite restart loop.
    alembic_version_empty = False
    if has_alembic_version:
        with engine.connect() as conn:
            row = conn.execute(sa.text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            alembic_version_empty = row is None

    untracked_db = (not has_alembic_version or alembic_version_empty) and partial_tables

    if untracked_db:
        if _initial_schema_tables.issubset(existing_tables):
            # All app tables present but Alembic has no record of them.  Stamp at
            # the initial revision so upgrade() only runs newer migrations on top.
            logger.info(
                "init_db: untracked database detected (alembic_version %s); "
                "stamping to d8524591de41 then upgrading to head.",
                "empty" if alembic_version_empty else "missing",
            )
            command.stamp(alembic_cfg, "d8524591de41")
            command.upgrade(alembic_cfg, "head")
        else:
            # Partial state: some tables exist (from an interrupted previous migration run)
            # but not all.  Drop them so a clean upgrade can proceed.
            logger.warning(
                "init_db: partial database state detected (present: %s, missing: %s). "
                "Dropping partial tables and re-running migrations.",
                sorted(partial_tables),
                sorted(_initial_schema_tables - partial_tables),
            )
            with engine.begin() as conn:
                conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
                for tbl in sorted(partial_tables):
                    logger.warning("init_db: dropping table %s", tbl)
                    conn.execute(sa.text(f"DROP TABLE IF EXISTS [{tbl}]"))
                conn.execute(sa.text("PRAGMA foreign_keys=ON"))
            command.upgrade(alembic_cfg, "head")
    else:
        try:
            command.upgrade(alembic_cfg, "head")
        except Exception:
            logger.exception("init_db: Alembic upgrade failed — DB state: tables=%s", sorted(existing_tables))
            raise
