"""add canonical_url to url_sources

The duplicate check on url_sources compared the raw "url" string, so
visually different URLs pointing at the same video (youtu.be vs
youtube.com, www. vs no subdomain, differing query-param order, share
tracking params like "si") were treated as distinct sources. This adds a
canonical_url column populated by app.schemas.normalize_youtube_url() and
backed by a unique index, so the API can reject true duplicates instead of
only exact string matches.

Existing rows are backfilled with their normalized URL. If two existing
rows would normalize to the same canonical value (already-duplicated data
under the old exact-match check), the later row keeps a row-id-suffixed
key instead of failing the migration — this only affects historical rows;
new inserts going through the app are deduped going forward.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union
from urllib.parse import parse_qsl, urlencode, urlparse

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TRACKING_PARAMS = {"si", "feature", "pp", "ab_channel", "t", "time_continue", "app"}


def _normalize_youtube_url(v: str) -> str:
    parsed = urlparse(v)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/")
    query = dict(parse_qsl(parsed.query))

    if host == "youtu.be":
        video_id = path.lstrip("/").split("/")[0]
        if video_id:
            return f"video:{video_id}"
    else:
        segments = [s for s in path.split("/") if s]
        segments_lower = [s.lower() for s in segments]
        if segments_lower and segments_lower[0] in ("shorts", "embed", "live") and len(segments) > 1:
            return f"video:{segments[1]}"
        if segments_lower and segments_lower[0] == "watch" and query.get("v"):
            return f"video:{query['v']}"
        if segments_lower and segments_lower[0] == "playlist" and query.get("list"):
            return f"playlist:{query['list']}"
        if segments_lower and segments_lower[0] == "channel" and len(segments) > 1:
            return f"channel:{segments[1]}"
        if segments_lower and segments_lower[0] in ("c", "user") and len(segments) > 1:
            return f"channel:{segments_lower[0]}/{segments[1]}"
        if segments and segments[0].startswith("@"):
            return f"channel:{segments[0].lower()}"

    normalized_host = host[4:] if host.startswith("www.") else host
    kept_query = sorted((k, val) for k, val in parse_qsl(parsed.query) if k not in _TRACKING_PARAMS)
    query_str = urlencode(kept_query)
    return f"url:{normalized_host}{path}?{query_str}" if query_str else f"url:{normalized_host}{path}"


def upgrade() -> None:
    op.add_column("url_sources", sa.Column("canonical_url", sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, url FROM url_sources ORDER BY id")).fetchall()

    seen: set[str] = set()
    for row_id, url in rows:
        canonical = _normalize_youtube_url(url)
        if canonical in seen:
            canonical = f"{canonical}::dup{row_id}"
        seen.add(canonical)
        bind.execute(
            sa.text("UPDATE url_sources SET canonical_url = :c WHERE id = :i"),
            {"c": canonical, "i": row_id},
        )

    with op.batch_alter_table("url_sources") as batch:
        batch.alter_column("canonical_url", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint("uq_url_sources_canonical_url", ["canonical_url"])


def downgrade() -> None:
    with op.batch_alter_table("url_sources") as batch:
        batch.drop_constraint("uq_url_sources_canonical_url", type_="unique")
        batch.drop_column("canonical_url")
