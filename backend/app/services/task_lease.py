"""Renewable Redis leases shared by API, scheduler and worker processes."""

from contextvars import ContextVar
from functools import wraps
from threading import Event, Thread

from redis.exceptions import LockError, RedisError

from app.config import settings

_current = ContextVar("task_lease", default=None)


class LeaseLost(RuntimeError):
    pass


def check_lease():
    current = _current.get()
    if current is not None:
        lost, lock = current
        if lost.is_set() or not lock.owned():
            raise LeaseLost("Task lease expired; refusing to publish stale results")


def exclusive_task(client, namespace, on_busy=None):
    def decorate(fn):
        @wraps(fn)
        def run(self, record_id, *args, **kwargs):
            ttl = settings.sync_lock_timeout_seconds
            lock = client().lock(
                f"lmp:{namespace}:{record_id}", timeout=ttl, thread_local=False
            )
            try:
                if not lock.acquire(blocking=False):
                    if on_busy is not None:
                        return on_busy(self, record_id)
                    return  # Another worker owns this exact operation.
            except RedisError as exc:
                raise self.retry(exc=exc, countdown=10)
            stopped, lost = Event(), Event()

            def renew():
                while not stopped.wait(ttl / 3):
                    try:
                        lock.extend(ttl, replace_ttl=True)
                    except (RedisError, LockError):
                        lost.set()
                        return

            thread = Thread(target=renew, daemon=True)
            token = _current.set((lost, lock))
            thread.start()
            try:
                return fn(self, record_id, *args, **kwargs)
            finally:
                stopped.set()
                thread.join(timeout=2)
                _current.reset(token)
                try:
                    lock.release()
                except (RedisError, LockError):
                    pass  # A dead worker's lease expires; never release another owner's lease.

        return run

    return decorate
