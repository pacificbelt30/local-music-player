from threading import Event
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import LockNotOwnedError

from app.services.task_lease import exclusive_task, check_lease, LeaseLost


def test_lease_renews_during_long_operations_and_releases_on_error(monkeypatch):
    monkeypatch.setattr('app.services.task_lease.settings.sync_lock_timeout_seconds',6)
    lock=MagicMock();renewed=Event();lock.extend.side_effect=lambda *a,**k:renewed.set()
    client=MagicMock();client.lock.return_value=lock
    @exclusive_task(lambda:client,'test')
    def operation(self,record_id):
        assert renewed.wait(4)
        check_lease()
        raise ValueError('task failed')
    with pytest.raises(ValueError):operation(MagicMock(),1)
    lock.extend.assert_called_with(6,replace_ttl=True)
    lock.release.assert_called_once()


def test_lost_ownership_cannot_publish_or_release_another_lease():
    lock=MagicMock();lock.owned.return_value=False;lock.release.side_effect=LockNotOwnedError('expired')
    client=MagicMock();client.lock.return_value=lock
    @exclusive_task(lambda:client,'test')
    def operation(self,record_id):check_lease()
    with pytest.raises(LeaseLost):operation(MagicMock(),1)


def test_duplicate_operation_does_not_run_or_release_the_owner():
    lock=MagicMock();lock.acquire.return_value=False;client=MagicMock();client.lock.return_value=lock
    work=MagicMock()
    operation=exclusive_task(lambda:client,'test')(work)
    operation(MagicMock(),1)
    work.assert_not_called();lock.release.assert_not_called()
