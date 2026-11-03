"""Legacy downloads survive upgrade, downgrade and a repeated upgrade."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_workspace_migration_preserves_existing_downloads(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    path = tmp_path / "legacy-workspace.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}

    def migrate(*args):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(backend / "alembic.ini"),
                *args,
            ],
            cwd=backend,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )

    migrate("upgrade", "18b9c0d1e2f3")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO youtube_playlist_syncs(id,playlist_id,playlist_name,audio_format,audio_quality,enabled) VALUES(1,'legacy','Legacy','mp3','192',1)"
        )
        conn.execute(
            "INSERT INTO playlist_sync_tracks(id,playlist_sync_id,youtube_id,title,status,file_path) VALUES(1,1,'vid','Saved','complete','/downloads/Legacy/saved.mp3')"
        )
    migrate("upgrade", "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT title,file_path,status,removed_at,keep_local,excluded FROM playlist_sync_tracks"
        ).fetchone() == ("Saved", "/downloads/Legacy/saved.mp3", "complete", None, 0, 0)
        assert conn.execute(
            "SELECT profile_id,target_scope FROM youtube_playlist_syncs"
        ).fetchone() == (None, "downloads")
        conn.execute(
            "INSERT INTO media_profiles(id,name,audio_format,audio_quality) VALUES(1,'Phone','m4a','192')"
        )
        conn.execute(
            "INSERT INTO sync_events(sync_id,kind,details) VALUES(1,'sync','{}')"
        )
    migrate("downgrade", "18b9c0d1e2f3")
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT file_path,status FROM playlist_sync_tracks"
        ).fetchone() == ("/downloads/Legacy/saved.mp3", "complete")
    migrate("upgrade", "head")
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT keep_local,excluded FROM playlist_sync_tracks"
        ).fetchone() == (0, 0)
