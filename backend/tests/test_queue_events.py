"""Progress streaming does not block API work or read Redis once per job."""

import asyncio
import json
import threading
from unittest.mock import patch

from app.api import queue
from app.models import DownloadJob


def test_progress_for_many_jobs_uses_one_redis_round_trip(db):
    db.add_all(
        [
            DownloadJob(youtube_id=f"v{i}", status="downloading", progress_pct=12)
            for i in range(100)
        ]
    )
    db.add(DownloadJob(youtube_id="finished", status="complete"))
    db.commit()
    with (
        patch.object(
            queue._redis, "mget", return_value=["0", None] + ["65"] * 98
        ) as mget,
        patch.object(queue._redis, "get") as get,
    ):
        result = queue._queue_snapshot()
    assert len(result) == 100
    assert result[0]["progress_pct"] == 0
    assert result[1]["progress_pct"] == 12
    assert all(row["progress_pct"] == 65 for row in result[2:])
    assert len(mget.call_args.args[0]) == 100
    mget.assert_called_once()
    get.assert_not_called()


def test_empty_queue_does_not_contact_redis(db):
    with patch.object(queue._redis, "mget") as mget:
        assert queue._queue_snapshot() == []
    mget.assert_not_called()


def test_active_jobs_stay_visible_even_with_many_newer_failures(client, db):
    db.add(DownloadJob(youtube_id="active", status="pending"))
    db.commit()
    db.add_all(
        [DownloadJob(youtube_id=f"fail{i}", status="failed") for i in range(220)]
    )
    db.commit()
    records = client.get("/api/v1/queue?status=pending,downloading,failed").json()
    assert len(records) == 200
    assert records[0]["youtube_id"] == "active"


def test_stream_window_matches_list_when_more_than_200_jobs_are_active(client, db):
    db.add_all([DownloadJob(youtube_id=f"v{i}", status="pending") for i in range(215)])
    db.commit()
    with patch.object(queue._redis, "mget", return_value=[None] * 200):
        snapshot = queue._queue_snapshot()
    records = client.get("/api/v1/queue?status=pending,downloading,failed").json()
    assert [r["job_id"] for r in snapshot] == [r["id"] for r in records]


def test_stream_runs_blocking_snapshot_off_the_event_loop():
    started, release = threading.Event(), threading.Event()
    threads = []

    def slow_snapshot(**kwargs):
        threads.append(threading.get_ident())
        started.set()
        release.wait(1)
        return []

    async def scenario():
        response = await queue.queue_events()
        pending = asyncio.create_task(anext(response.body_iterator))
        try:
            await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
            assert not pending.done(), "other API tasks must run while Redis waits"
            assert threads != [threading.get_ident()]
        finally:
            release.set()
        assert json.loads((await pending).removeprefix("data: ").strip()) == []
        await response.body_iterator.aclose()
        assert response.headers["x-accel-buffering"] == "no"

    with patch.object(queue, "_queue_snapshot", side_effect=slow_snapshot):
        asyncio.run(scenario())


def test_stream_does_not_probe_workers_every_second():
    async def no_wait(_):
        pass

    async def scenario():
        response = await queue.queue_events()
        await anext(response.body_iterator)
        await anext(response.body_iterator)
        await response.body_iterator.aclose()

    with (
        patch.object(queue, "_queue_snapshot", return_value=[]) as snapshot,
        patch.object(queue.asyncio, "sleep", no_wait),
    ):
        asyncio.run(scenario())
    assert [call.kwargs["recover"] for call in snapshot.call_args_list] == [True, False]


def test_snapshot_closes_session_even_if_redis_disconnects(db):
    db.add(DownloadJob(youtube_id="active", status="pending"))
    db.commit()
    from app.database import SessionLocal

    session = SessionLocal()
    with (
        patch("app.database.SessionLocal", return_value=session),
        patch.object(session, "close", wraps=session.close) as close,
        patch.object(queue._redis, "mget", side_effect=ConnectionError("offline")),
    ):
        try:
            queue._queue_snapshot()
        except ConnectionError:
            pass
        else:
            raise AssertionError("Redis outage must reach the stream reconnect handler")
        close.assert_called_once()
