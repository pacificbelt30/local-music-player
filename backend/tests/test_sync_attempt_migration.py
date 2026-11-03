"""An existing database gains nullable attempt metadata without losing tracks."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_attempt_metadata_upgrade_and_downgrade_preserves_legacy_tracks(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    path = tmp_path/"legacy.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}
    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", "-c", str(backend/"alembic.ini"), *args],
                       cwd=backend, env=env, check=True, capture_output=True, text=True, timeout=20)
    migrate("upgrade", "07a8b9c0d1e2")
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO youtube_playlist_syncs (id,playlist_id,playlist_name,audio_format,audio_quality,enabled) VALUES (1,'legacy','Legacy','mp3','192',1)")
        conn.execute("INSERT INTO playlist_sync_tracks (id,playlist_sync_id,youtube_id,title,status) VALUES (1,1,'legacy-video','Legacy track','downloading')")
    migrate("upgrade", "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT title,status,started_at,celery_task_id FROM playlist_sync_tracks").fetchone() == ("Legacy track", "downloading", None, None)
    migrate("downgrade", "07a8b9c0d1e2")
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(playlist_sync_tracks)")}
        assert "started_at" not in columns and "celery_task_id" not in columns
        assert conn.execute("SELECT title,status FROM playlist_sync_tracks").fetchone() == ("Legacy track", "downloading")
